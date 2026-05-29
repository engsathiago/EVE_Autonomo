# D.1 — Tool routing por step

> Sub-fase D do agente autônomo. Pré-requisito: `fase-b-done` mergeada em `main`, com `ToolCallSummary` + `analyze_turn()` validando execução real e rejeitando prose-only.

---

## 1. Contexto

A Fase A diagnosticou 10/14 fases como TEÓRICAS. A Fase B atacou o sintoma — "executor persiste sem validar" — adicionando `analyze_turn()` que rejeita `status=done` quando não houve `tool_use` real. Smoke B.6 com qwen3:30b validou o fix.

**Mas B.6 expôs outro problema**, independente do fix B: o subagente recebeu um step pedindo `write_file` e respondeu honestamente *"essa ferramenta não está disponível"*. Investigação confirmou: subagentes em tier STRATEGIC recebem set fixo de tools — `web_search`, `read_file`, `salvar_memoria`, `ler_memoria`. Sem `write_file`, sem `list_dir`, sem `exec_tool`.

Isso muda a leitura retrospectiva da Fase A. Parte das missões classificadas como TEATRO **não era** o LLM gerando prosa por vagabundagem — era o LLM **respondendo correto que não tinha a tool**. O agente foi configurado pra falhar nesses casos.

A D.1 conserta isso: tool set deixa de ser função do **tier** e passa a ser função do **step**. Cada step declara (ou o orchestrator infere) quais tools são necessárias, e o pool monta o subagente com exatamente esse conjunto.

A D.1 **não** mexe no executor (Fase B já fechou). **Não** mexe no Critic (D.4). **Não** mexe em timeout (D.2). Escopo é estreito de propósito: tool routing e nada mais.

---

## 2. Objetivos

1. Substituir `tier → tools_allowed` (estático) por `step → tools_required` (dinâmico).
2. Permitir que o orchestrator infira `tools_required` da intenção do step quando o autor da missão não declarou explicitamente.
3. Manter compatibilidade com missões antigas no DB (steps sem `tools_required` → infere ou usa default seguro).
4. Garantir que `exec_tool` continua sendo o ponto único de execução (não regredir F8).
5. Logar decisão de routing em `step_tool_routing` (nova tabela) pra auditoria.
6. Adicionar suite que prova que steps com tools faltantes **não rodam silenciosamente** — falham com erro claro `MissingRequiredTool`.

**Não-objetivos:**
- Não cria novas tools (só roteia as que já existem).
- Não mexe em sandbox profile (continua DEFAULT/SKILL_DEV/UNTRUSTED).
- Não muda contrato do Critic.
- Não toca em F9 (skills auto-geradas têm seu próprio routing via manifest).

---

## 3. Arquitetura

### 3.1 Modelo de dados

**Nova coluna em `mission_steps`:**
```sql
ALTER TABLE mission_steps
  ADD COLUMN tools_required JSONB NOT NULL DEFAULT '[]'::jsonb;
-- exemplo: ["web_search", "write_file"]
```

**Nova tabela `step_tool_routing`:**
```sql
CREATE TABLE step_tool_routing (
  id BIGSERIAL PRIMARY KEY,
  step_id BIGINT NOT NULL REFERENCES mission_steps(id) ON DELETE CASCADE,
  tier TEXT NOT NULL,
  tools_declared JSONB NOT NULL DEFAULT '[]'::jsonb,
  tools_inferred JSONB NOT NULL DEFAULT '[]'::jsonb,
  tools_resolved JSONB NOT NULL,
  inference_source TEXT NOT NULL CHECK (inference_source IN ('declared', 'inferred_keyword', 'inferred_llm', 'fallback_default')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_step_tool_routing_step ON step_tool_routing(step_id);
```

Migração: próxima disponível depois da B (confere antes — provavelmente `013_step_tool_routing.sql`).

### 3.2 Componentes

**Novo módulo `agent/orchestrator/tool_router.py`:**
- `resolve_tools_for_step(step: MissionStep, tier: Tier) -> ToolResolution`
- `ToolResolution` carrega: `tools` (lista final), `source` (declared/inferred_keyword/inferred_llm/fallback_default), `audit` (dict pra `step_tool_routing`)

**Estratégia de resolução, em ordem:**
1. Se `step.tools_required` é não-vazio → usa direto (`source=declared`).
2. Senão, tenta inferência por keyword no `step.description`:
   - `"escrever|salvar|write|file"` → adiciona `write_file`
   - `"ler|cat|read|abrir arquivo"` → adiciona `read_file`
   - `"listar|ls|dir"` → adiciona `list_dir`
   - `"buscar na web|pesquisar|search"` → adiciona `web_search`
   - `"memória|lembra|histórico"` → adiciona `salvar_memoria`, `ler_memoria`
   - `"executar|rodar|sh|bash|python"` → adiciona `exec_tool`
   (lista completa em `KEYWORD_TOOL_MAP` no módulo, fácil de auditar)
3. Se keyword não casou nada e tier é STRATEGIC/EPIC → chama LLM (Haiku) com prompt curto: "dado este step, quais tools são necessárias? responda JSON". Cacheado por hash do step. `source=inferred_llm`.
4. Fallback: tier INSTANT/FAST recebe `["web_search", "read_file", "salvar_memoria", "ler_memoria"]`; STRATEGIC/EPIC recebe **tudo que existir** (a disciplina vira do prompt, não da ausência). `source=fallback_default`.

**Modificações em `agent/subagents/context.py`:**
- `build_context(step, tier)` deixa de mapear `tier → tools_allowed` e passa a chamar `tool_router.resolve_tools_for_step(step, tier)`.
- Grava o `audit` em `step_tool_routing` antes de retornar.

**Modificações em `agent/subagents/pool.py`:**
- Antes de dispatch, valida: pra cada tool em `tools_required` declarado, checa se existe no registry. Se faltar uma tool **declarada** (não inferida), lança `MissingRequiredTool(step_id, missing=[...])` e marca step como `failed_missing_tool` (novo verdict).

**Modificações em `agent/orchestrator/tiers.py`:**
- Remove `TIER_TOOLS` estático. Marca deprecated por 1 versão pra não quebrar imports externos, depois remove.

### 3.3 Mudança no contrato de step

Steps em missões novas **podem** declarar `tools_required`:
```yaml
- step: "Buscar canal do Joel Jota no YouTube e salvar em /tmp/joel.json"
  tools_required: ["web_search", "write_file"]
```

Steps sem `tools_required` continuam funcionando — caem no inferidor.

### 3.4 Lint do orchestrator

Adiciona regra em `test_orchestrator_lint.py`:
- Nenhum módulo fora de `agent/orchestrator/tool_router.py` pode importar `KEYWORD_TOOL_MAP` ou montar lista de tools por tier manualmente.
- `agent/subagents/context.py` **deve** chamar `tool_router.resolve_tools_for_step`.

---

## 4. Critérios de aceitação

**C1 — Schema aplicado.** Migration nova roda limpa, `tools_required` em `mission_steps` defaulta `[]`, `step_tool_routing` criada com index.

**C2 — Resolução por declaração.** Step com `tools_required=["write_file"]` → subagente recebe exatamente `["write_file"]` (mais defaults seguros: `salvar_memoria`/`ler_memoria` sempre presentes). `source=declared` em `step_tool_routing`.

**C3 — Resolução por keyword.** Step `"Buscar X e salvar em /tmp/y"` sem `tools_required` → resolve `["web_search", "write_file", "salvar_memoria", "ler_memoria"]`. `source=inferred_keyword`.

**C4 — Resolução por LLM.** Step com descrição ambígua (sem keyword match) em tier STRATEGIC → chama Haiku, retorna JSON válido, resolve, cacheia pelo hash. Segunda execução do mesmo step não chama LLM. `source=inferred_llm`.

**C5 — Fallback default.** Step ambíguo em tier INSTANT → não chama LLM (custo), usa default `["web_search", "read_file", "salvar_memoria", "ler_memoria"]`. `source=fallback_default`.

**C6 — Tool declarada faltante = erro claro.** Step declara `tools_required=["tool_que_nao_existe"]` → subagente NÃO roda, step vira `failed_missing_tool`, missão segue sem travar.

**C7 — Backcompat.** Missões antigas (steps com `tools_required=[]`) processam usando inferidor. Nenhuma migração de dados destrutiva.

**C8 — exec_tool segue único.** Lint passa: nenhum módulo executa tool fora de `exec_tool`. Regressão da F8 = falha.

**C9 — Auditoria completa.** Pra cada step que rodou na suite, há exatamente uma linha em `step_tool_routing` com `tools_resolved` não-vazio.

**C10 — Replay da Fase A.** Roda subset de 5 missões marcadas TEATRO na Fase A com fix D.1 ativo. Pelo menos 2 delas mudam de `failed_no_execution` pra `done` legítimo (com tool calls reais). Documenta em `D1_REPLAY_RESULTS.md`.

**Não é critério, mas vale notar:** se C10 mostrar 0 mudanças, D.1 não destrancou nada e precisa investigação adicional antes de fechar.

---

## 5. Anti-padrões a evitar

- **Não inferir LLM em tier INSTANT/FAST.** Custo não justifica latência pra steps rápidos.
- **Não dar `exec_tool` por inferência keyword sem segunda checagem.** Keyword "executar" pode ser metáfora ("vamos executar o plano"). Em caso de dúvida, pergunta ao Haiku ou rebaixa pra `web_search`.
- **Não silenciar `MissingRequiredTool`.** O ponto inteiro da D.1 é tornar visível o que estava escondido. Se uma tool falta, falha rápido e loud.
- **Não acoplar tool router ao Critic (D.4).** D.1 é routing. Critic decide se step deve rodar. Coisas separadas.
- **Não inferir tool baseado em conteúdo do trace anterior.** Inferência olha só pro step atual + tier. Histórico vira ruído.

---

## 6. Entregáveis

1. `core/src/agent/orchestrator/tool_router.py` (novo, ~250 linhas)
2. `core/src/agent/orchestrator/__init__.py` (export do `resolve_tools_for_step`)
3. Migration `013_step_tool_routing.sql` (ou próximo número disponível)
4. Modificações em `agent/subagents/context.py` (~30 linhas tocadas)
5. Modificações em `agent/subagents/pool.py` (~50 linhas — adiciona validação + verdict novo)
6. Modificações em `agent/orchestrator/tiers.py` (~20 linhas — deprecate TIER_TOOLS)
7. Modificações em `agent/missions/executor.py` (~15 linhas — propaga `failed_missing_tool`)
8. `tests/tool_router/test_resolution.py` (8-10 testes)
9. `tests/tool_router/test_integration.py` (4-6 testes E2E com DB real)
10. `tests/orchestrator/test_lint_d1.py` (regra de lint nova)
11. `docs/phases/D1_NOTES.md` (decisões + KEYWORD_TOOL_MAP documentado)
12. `D1_REPLAY_RESULTS.md` (resultado do C10)

---

## 7. Estado final

- Branch: `feature/d1-tool-routing`
- Tag: `d1-done` ao fim
- Suite: tudo verde, incluindo `tests/tool_router/` e regressão Fase B
- Replay de 5 missões TEATRO documentado
- `FASE_D_BACKLOG.md` atualizado: marca D.1 como `[done]`, anota se algum efeito foi observado em D.2/D.4/D.5
