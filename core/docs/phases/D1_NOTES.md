# D.1 — Tool Routing por Step: Notas de Implementação

> Branch: `feature/d1-tool-routing`
> Data: 2026-05-27

---

## 1. Decisões de design

### 1.1 TIER_TOOLS: shim deprecated em vez de remoção imediata

O símbolo `TIER_TOOLS` foi removido como fonte de verdade e substituído
por `resolve_tools_for_step()`, mas mantido como `__getattr__` shim em
`orchestrator/tiers.py` com `DeprecationWarning`.

**Por quê:** imports externos (CLI, testes de terceiros) que referenciam
`TIER_TOOLS` diretamente não devem quebrar em uma única atualização.
O shim emite warning visível sem causar `ImportError`. Remoção ocorre em D.2+.

O shim foi implementado **apenas** em `tiers.py` — não em `tool_router.py`
(tentativa inicial foi revertida porque criou referência duplicada que
violava o lint L1).

---

### 1.2 Validação só quando source=declared

O pool valida `tools_required` contra o registry **somente** quando
`context.tools_required` é não-vazio, o que só acontece quando
`resolution.source == "declared"`.

**Por quê:** quando as tools foram inferidas (keyword, LLM, fallback),
o inferidor já filtra para `KNOWN_BUILTIN_TOOLS`. Qualquer sugestão de
tool inexistente é descartada silenciosamente no filtro. Validar inferidas
como se fossem "obrigatórias" causaria falhas em tools que o step nem
pediu explicitamente — confusão de causa/efeito.

O contrato é: **se você declarou, eu valido. Se eu inferi, eu garanto
que só usarei o que existe.**

---

### 1.3 `failed_missing_tool` é terminal mas não trava a missão

O status `failed_missing_tool` entra em `_TERMINAL_STATUSES` do
`MissionStore` para completar o `completed_at` do step.

No `autonomous/loop.py`, `_process_mission` considera como terminal
`{"done", "skipped", "failed_missing_tool"}`. Quando todos os steps
atingem um desses estados, a missão é marcada como `completed`.

**Por quê:** ausência de tool é erro de **configuração**, não de
**execução** — não existe retry que resolva. A missão pode completar
parcialmente. Se o operador precisar reprocessar o step, ele conserta
o `tools_required` e cria nova missão.

Não incrementa `retry_count` para não confundir com falhas de execução
reais que merecem retry.

---

### 1.4 LLM inference só em STRATEGIC/EPIC

Tiers INSTANT e FAST não chamam Haiku para inferência — caem direto no
fallback `["web_search", "read_file", "salvar_memoria", "ler_memoria"]`.

**Por quê:** latência e custo de uma chamada LLM (mesmo Haiku) é
desproporcionalmente alto para steps de 1-2 tool calls que INSTANT/FAST
esperam. O default conservador cobre >90% dos casos nesses tiers.

STRATEGIC/EPIC justificam o custo porque:
1. São execuções longas — overhead de ~100ms de LLM é irrelevante.
2. A escolha errada de tools causa steps inteiros a falhar (custo muito maior).

---

### 1.5 `tools_required` propagado via `Task` (não estava no spec original)

O spec original descrevia a propagação de `tools_required` como sendo
feita em `context.py`, mas `context.py` não tem acesso ao `MissionStep`
— recebe apenas `task` (str).

Solução implementada: adicionado `tools_required: list[str]` ao dataclass
`Task`, que o `autonomous/loop.py` preenche com `step.tools_required` ao
criar a task. O orchestrator lê de `task.tools_required` antes de chamar
`resolve_tools_for_step`.

Isso mantém a separação de responsabilidades: loop conhece steps, task
carrega o dado, orchestrator decide a resolução.

---

## 2. KEYWORD_TOOL_MAP — mapeamento completo

```python
KEYWORD_TOOL_MAP = {
    # Escrita de arquivo
    r"\b(escrever|salvar arquivo|salvar em|write.?file|gravar|criar arquivo)\b": ["write_file"],
    # Leitura de arquivo
    r"\b(ler arquivo|abrir arquivo|read.?file|cat |conteúdo do arquivo|lê o arquivo)\b": ["read_file"],
    # Listagem de diretório
    r"\b(listar|ls |list.?dir|ls$|diretório|directory listing)\b": ["list_dir"],
    # Busca na web (específica)
    r"\b(buscar na web|pesquisar na web|search the web|web search|pesquisa online|procurar online)\b": ["web_search"],
    # Busca genérica (menor prioridade)
    r"\b(pesquisar|buscar|search|procurar)\b": ["web_search"],
    # Memória
    r"\b(memória|lembrar|lembra|histórico de memória|memory store)\b": ["salvar_memoria", "ler_memoria"],
    # Shell — exige contexto técnico explícito (anti-padrão §5)
    r"\b(rodar script|executar script|bash |sh |python .+\.py|shell command|run command|execute command)\b": ["shell"],
}
```

**Notas sobre o mapeamento:**

- `"executar"` sozinho **não** aciona `shell`. O spec §5 diz: "keyword
  'executar' pode ser metáfora". O padrão exige `executar script` ou
  sinônimos técnicos explícitos.
- Busca tem dois padrões: específico (`buscar na web`) e genérico
  (`pesquisar`). O genérico está por último — se a descrição tiver
  keyword mais específico que já gerou match, o genérico não acrescenta
  tool diferente.
- `ALWAYS_TOOLS = ["salvar_memoria", "ler_memoria"]` são adicionadas
  ao resultado final em toda estratégia — sem exceção.

---

## 3. Edge cases descobertos durante implementação

### 3.1 Migration 016 em vez de 013

O spec previa `013_step_tool_routing.sql` mas migrations `013`, `014` e
`015` já existiam (channel_messages, finetune, executor_validation).
Arquivo correto: `016_step_tool_routing.sql`.

### 3.2 DROP + ADD no CHECK constraint

PostgreSQL não suporta `ALTER TABLE ... MODIFY CONSTRAINT`. Para adicionar
`failed_missing_tool` ao CHECK de `mission_steps.status`, foi necessário:
```sql
ALTER TABLE mission_steps DROP CONSTRAINT IF EXISTS mission_steps_status_check;
ALTER TABLE mission_steps ADD CONSTRAINT mission_steps_status_check CHECK (...);
```
Isso é seguro porque o DROP é `IF EXISTS` e rows existentes não violam
o novo constraint (apenas adiciona um valor permitido, não remove nenhum).

### 3.3 `row.get()` vs `row[]` em `_row_to_step`

`asyncpg.Record` suporta `row["column"]` mas **não** `row.get("column", default)`.
Para compatibilidade retroativa com rows de DBs que ainda não rodaram a migration 016
(e com mocks de teste que usam `MagicMock(spec=asyncpg.Record)`), a leitura de
`tools_required` usa:
```python
row.get("tools_required", "[]") if hasattr(row, "get") else "[]"
```
Isso garante que testes unitários que mockem `asyncpg.Record` sem o campo
não quebrem.

### 3.4 `ToolResolution` com campos diretos além de `audit`

O spec original definia `audit: dict` como único payload de rastreabilidade.
Durante os testes, ficou claro que o teste `test_keyword_metafora_executar_nao_aciona_shell`
precisava acessar `tools_inferred` diretamente (não via `audit["tools_inferred"]`).

Adicionados `tools_declared: list[str]` e `tools_inferred: list[str]` como campos
de primeiro nível em `ToolResolution` (espelham o audit para acesso tipado).

### 3.5 Regressão Fase B: `test_no_prose_done.py`

`_make_step()` usava `MagicMock(spec=MissionStep)` sem setar `tools_required`.
D.1 adicionou `step.tools_required` ao loop, causando `AttributeError`. Fix:
adicionar `s.tools_required = []` ao mock helper.

Este padrão pode existir em outros testes de fase futura que mockam `MissionStep`.
**TODO**: considerar criar um helper centralizado `make_mission_step_mock()` que
seta todos os campos padrão, incluindo `tools_required=[]`.

### 3.6 Shim TIER_TOOLS duplicado

Implementação inicial adicionou o `__getattr__` shim em **dois** módulos:
`tiers.py` e `tool_router.py`. O lint L1 detectou a duplicata. Removido de
`tool_router.py` — shim só existe em `tiers.py`.

---

## 4. Débitos técnicos criados

| ID | Descrição | Impacto | Resolve em |
|----|-----------|---------|-----------|
| DT-D1-1 | `TIER_TOOLS` shim em `tiers.py` precisa ser removido | Baixo — só emite warning | D.2+ |
| DT-D1-2 | `_make_step()` helper centralizado para mocks de `MissionStep` | Médio — outros testes podem ter o mesmo problema | Manutenção |
| DT-D1-3 | `log_routing_audit` não tem retry em caso de falha de DB | Baixo — audit é best-effort por design | D.3+ |
| DT-D1-4 | `Task.tools_required` não é persistido no banco (tabela `tasks`) | Médio — perde rastreabilidade em tasks de missão se reiniciar durante execução | D.3+ |
| DT-D1-5 | `_llm_cache` é module-level dict (sobrevive a reload mas não a restart) | Baixo — TTL 7d é muito longo para in-memory sem persistência | D.3+ |

---

## 5. TODOs descobertos no caminho

- **EPIC tier**: `_run_epic()` no orchestrator nunca passa `tools_required` das
  subtasks porque EPIC decompõe em subtasks via LLM (sem step original). Se
  EPIC vier de uma missão planejada, as tools_required do step EPIC original
  ficam perdidas. Investigar em D.2.

- **`AutonomousLoop._process_mission`**: a checagem de `completed` usa
  `{"done", "skipped", "failed_missing_tool"}` como terminal. Mas `"failed"`
  e `"failed_no_execution"` não entram — missão pode ficar travada se todos
  os steps estiverem em `failed`. Esse comportamento é pré-D.1; apenas
  documentado aqui.

---

## 6. O que o Replay C10 vai medir

O replay C10 toma 5 missões marcadas como TEATRO na Fase A e executa
com fix D.1 ativo, verificando se elas mudam de `failed_no_execution`
para `done` com tool calls reais.

**Hipótese a ser testada:**

> Parte das missões TEATRO na Fase A não era "preguiça do LLM" — era
> o LLM reportando corretamente que as tools necessárias não estavam
> disponíveis no contexto (confirm por smoke B.6 com qwen3:30b).

**Baseline antes do replay:**
- Tools disponíveis em STRATEGIC antes de D.1: `["web_search", "read_file",
  "salvar_memoria", "ler_memoria"]`
- Tools disponíveis em STRATEGIC após D.1 (fallback): todas as builtin
  (`read_file`, `write_file`, `list_dir`, `shell`, `web_search`,
  `salvar_memoria`, `ler_memoria`, `delegate`)

**Se C10 mostrar ≥ 2 missões mudando de TEATRO para done**: D.1 confirmado
como fix da causa raiz.

**Se C10 mostrar 0 mudanças**: D.1 não destrancou nada. Investigação adicional
necessária antes de fechar (hipótese original sobre tools estava incorreta).

O replay ainda não foi executado. Resultado em `D1_REPLAY_RESULTS.md`.
