# FASE_D_BACKLOG — achados pendentes da Fase B

> Gerado em 2026-05-26 ao fechar Fase B.
> Não bloqueiam o merge — são problemas independentes descobertos durante validação.

---

## D.1 — Tool routing por step (arquitetura)

**Descoberta:** durante B.6, qwen3:30b respondeu "write_file não está disponível" num step que pedia write_file. Investigação mostrou que subagentes em tier STRATEGIC recebem set fixo de tools (`web_search`, `read_file`, `salvar_memoria`, `ler_memoria`) — sem `write_file` ou `list_dir`.

**Hipótese:** parte das missões classificadas como TEATRO na Fase A pode ter sido o LLM respondendo honestamente que não tinha a tool, não puramente prosa-sem-execução.

**Proposta:** o orchestrator deveria escolher tools por step (baseado na descrição/intenção), não por tier fixo. Ou: subagente STRATEGIC deve ter todas as tools disponíveis e o prompt cuida da disciplina.

**Prioridade:** ALTA — possivelmente o motivo principal das 10 fases TEÓRICAS funcionarem mal mesmo após Fase B.

**Onde olhar:** `core/src/agent/subagents/context.py`, `core/src/agent/orchestrator/tiers.py`, mapeamento tier → tools_allowed.

---

## D.2 — Timeout de subagente vs modelo local lento

**Descoberta:** qwen3:30b local levou >60s para responder em B.6 (timeout default). Resultado: prose_only por timeout, não por falha do LLM.

**Proposta:** timeout adaptativo por modelo (Anthropic ~10s, Ollama local 30B Q4 ~120s). Ou: rebaixar tier pra modelos pequenos quando rodando 100% local.

**Prioridade:** MÉDIA — só afeta cenário 100% Ollama local. VPS com Anthropic não é afetada.

**Onde olhar:** `core/src/agent/subagents/pool.py` (timeout), config de timeouts por tier/provider.

---

## D.3 — FK violation em model_invocations (cosmético)

**Descoberta:** smoke test gerou warning `model_invocations FK violation` por session_id sem conversa prévia.

**Proposta:** ou tornar `session_id` nullable, ou criar session ghost para invocations de smoke/cron sem conversa parent.

**Prioridade:** BAIXA — só warning, não bloqueia funcionalidade.

**Onde olhar:** schema de `model_invocations`, `core/src/agent/models/router.py:271` (record).

---

## D.4 — Critic não conectado ao mission flow (adiado da Fase B)

**Descoberta original:** Fase A — 9 `critic_evaluations` órfãs, nenhuma com `mission_id` ou `task_id`. Critic existe, está wired no server.py, mas nunca é acionado pelo loop de missões.

**Análise da Fase B (BUG_PATTERN_MAP.md):** o ponto de intercepção precisa ser dentro de `AIAgent._execute_tools()` (pré-execução de tool específica), não em `_dispatch_step` (pré-dispatch de step genérico). O `Decision` criado no loop tem `tool_name="orchestrator_dispatch"` genérico — nunca casa com lista de irreversíveis.

**Proposta:** hook em `AIAgent._execute_tools` que, antes de cada tool call:
1. Verifica se tool está na lista de irreversíveis
2. Se sim: chama `critic.evaluate(Decision(tool_name=real_name, tier=...))`
3. Bloqueia se Critic rejeitar (`status='blocked_by_critic'` — novo status)

**Prioridade:** ALTA quando o sistema voltar a rodar autônomo em produção. Sem isso, decisões irreversíveis passam sem revisão.

**Onde olhar:** `core/src/agent/core.py:303` (`_execute_tools`), `core/src/agent/critic/irreversible.py`, schema mission_steps (novo status).

---

## D.5 — Re-validação F5–F13 em runtime real

**Pendente da Fase A:** 10 fases marcadas TEÓRICAS (F5 Telegram, F6 Cron, F7 Critic, F8 Sandbox, F9 Voyager, F10 Deploy, F11 Web UI, F12 Channels, F13 LoRA).

Com o fix da Fase B aplicado, algumas dessas fases podem começar a funcionar de graça quando exercitadas em runtime real (especialmente F6, F7, F8). Outras (F9, F11, F12, F13) precisam de validação independente.

**Proposta:** missão real por fase, em runtime, com critérios de aceite por DB count + efeito verificável. Re-escrever `AUDIT_REPORT.md` com status real após validação.

**Prioridade:** MÉDIA — pré-requisito para qualquer claim de "sistema pronto pra produção".
