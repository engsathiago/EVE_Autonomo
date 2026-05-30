# Issues Conhecidos

> Issues identificados durante a auditoria de execução real (Fase A, 2026-05-25)
> e durante a validação das melhorias D.1–D.6 (mai/2026).
>
> **Nenhum destes foi corrigido neste documento.** Cada issue tem uma referência
> ao backlog (`docs/phases/FASE_D_BACKLOG.md`) ou ao código onde a correção deve ocorrer.

---

## Arquitetura / Comportamento

### [KI-1] Critic não conectado ao mission flow

**Arquivo:** `core/src/agent/core.py:303` (`_execute_tools`)
**Ref backlog:** D.4 em `docs/phases/FASE_D_BACKLOG.md`

O `Critic` (3 personas: técnico, advogado do diabo, sintetizador) existe e está wired
no `server.py`, mas nunca é acionado pelo loop de missões em runtime. As 9 entradas
em `critic_evaluations` no banco foram criadas diretamente via API ou por testes de
integração — nenhuma tem `mission_id` ou `task_id` preenchido.

**Impacto:** ações irreversíveis de missões passam sem revisão do Critic.
**Prioridade:** ALTA quando o sistema voltar a rodar autônomo em produção.

---

### [KI-2] Timeout fixo de subagente (não adaptativo por modelo)

**Arquivo:** `core/src/agent/subagents/pool.py`
**Ref backlog:** D.2 em `docs/phases/FASE_D_BACKLOG.md`

O timeout de subagentes é fixo por tier (ex: STRATEGIC = 60s). Modelos locais grandes
(qwen3:30b, Llama 70B Q4) levam mais de 60s para responder, causando timeout silencioso
que resulta em prosa/TEATRO — o LLM não consegue completar a resposta antes do corte.

**Impacto:** apenas em cenários 100% Ollama local com modelos grandes. VPS com Anthropic
não é afetada.
**Prioridade:** MÉDIA.

---

### [MI-3] FK violation em `model_invocations`

**Arquivo:** `core/src/agent/models/router.py:271` (método `record`)
**Ref backlog:** D.3 em `docs/phases/FASE_D_BACKLOG.md`

Invocações LLM feitas por smoke tests e jobs de cron (sem conversa parent) geram warning
de FK violation porque `session_id` é obrigatório mas não existe conversa prévia.

**Impacto:** warning nos logs; não bloqueia funcionalidade.
**Prioridade:** BAIXA (cosmético).

---

### [KI-4] Curator sem deduplicação efetiva

**Arquivo:** `core/src/agent/memory/` (Curator)
**Ref:** EXECUTION_AUDIT §2, seção F2

O Curator decide o que persistir em memória, mas não faz deduplicação antes de salvar.
Resultado: 12 das 15 memórias no banco são variações da mesma frase
(`"O usuário prefere respostas concisas e diretas"`). A funcionalidade básica existe,
mas o critério de qualidade está ausente.

**Impacto:** banco de memória cresce com duplicatas; busca semântica pode retornar
o mesmo resultado múltiplas vezes.
**Prioridade:** MÉDIA.

---

### [KI-5] SkillCreator nunca exercitado em runtime

**Arquivo:** `core/src/agent/skills/creator.py`
**Ref:** EXECUTION_AUDIT §2, seção F3

O `SkillCreator` (extração de sessão → draft de skill) existe e tem testes unitários,
mas nunca foi acionado em runtime real. A coluna `skill_invocations` tem 4 entradas
referentes a skills builtin YAML (`summarize_text`, `web_research`), não a skills
criadas dinamicamente.

**Impacto:** funcionalidade de auto-criação de skills (inspirada no Voyager) é TEÓRICA.
**Prioridade:** ALTA quando D.5 (re-validação) for executado.

---

### [KI-6] `tools_used` em `subagent_runs` é enganoso

**Arquivo:** `core/src/agent/subagents/pool.py` (campo `tools_used` no resultado)
**Ref:** EXECUTION_AUDIT §5

O campo `tools_used` em `subagent_runs` registra as tools **disponíveis no contexto
do subagente**, não as que foram **efetivamente executadas**. Isso faz com que runs
de TEATRO (só prosa, zero tool calls) apareçam com `tools_used != []` no banco.

**Impacto:** métricas e dashboards que usem `tools_used` para medir atividade real
são enganosos.
**Prioridade:** MÉDIA (schema fix + migration de limpeza de dados antigos).

---

## Fases teóricas (código existe, nunca exercitado em runtime)

Ver `docs/audit/PHASE_STATUS.md` para lista completa. Resumo das fases com mais impacto
prático se você for usar o sistema:

| Fase | O que nunca rodou |
|------|--------------------|
| F5 — Gateway/Telegram | Nenhuma mensagem Telegram enviada/recebida; nenhum approval gerado |
| F8 — Sandboxes | `exec_tool` nunca acionado; `sandbox_executions=0` |
| F9 — Skills Voyager | Nenhuma skill sintetizada; `skills table=0 rows` |
| F12 — Canais (Discord/Slack/Email) | `channel_messages=0` |
| F13 — Fine-tuning LoRA | `finetune_runs=0`; LoraTrainer nunca executado |

O próximo passo natural para validar estas fases é **D.5** (re-validação em runtime real),
que está no backlog com prioridade ALTA.

---

*Atualizado em 2026-05-30. Ver `docs/audit/EXECUTION_AUDIT.md` para dados brutos.*
