# FASE_D_BACKLOG — achados pendentes da Fase B

> Gerado em 2026-05-26 ao fechar Fase B.
> Não bloqueiam o merge — são problemas independentes descobertos durante validação.
> **Atualizado em 2026-05-28:** D.1 concluída.

---

## D.1 — Tool routing por step (arquitetura) ✅ DONE

**Descoberta:** durante B.6, qwen3:30b respondeu "write_file não está disponível" num step que pedia write_file. Investigação mostrou que subagentes em tier STRATEGIC recebem set fixo de tools (`web_search`, `read_file`, `salvar_memoria`, `ler_memoria`) — sem `write_file` ou `list_dir`.

**Hipótese:** parte das missões classificadas como TEATRO na Fase A pode ter sido o LLM respondendo honestamente que não tinha a tool, não puramente prosa-sem-execução.

**Resolução:** implementada em `feature/d1-tool-routing`, mergeada em `main` em 2026-05-28.
- `resolve_tools_for_step()` substitui set fixo por tier → 4 estratégias: declared > keyword > LLM > fallback
- Migration 016: `tools_required JSONB` em `mission_steps`, tabela `step_tool_routing`, status `failed_missing_tool`
- Suite 40/40 verde. Tag: `d1-done`

**Replay C10:** 4/5 execuções mudaram de TEATRO para executed.
Relatório completo: [`core/docs/phases/D1_REPLAY_RESULTS.md`](core/docs/phases/D1_REPLAY_RESULTS.md)

**Limitações abertas (não bloqueadoras — ver L1/L2/L3 no relatório):**
- L1: replay rodou com Ollama; confirmar com Anthropic após 2026-06-01
- L2: C10-write-test ficou prose_only — ver D1-FU-1 abaixo (condicional)
- L3: steps sintéticos; replay histórico real em D.5

---

## D1-FU-1 — Investigar write_file prose_only (condicional) 🔒

**Origem:** limitação L2 do replay C10. Condicional: só abre se Anthropic também falhar no re-run pós 2026-06-01.

**Descrição:** no replay C10-write-test, `qwen2.5:7b` recebeu `write_file` corretamente no contexto mas não a invocou. Esse comportamento é diferente do bug D.1 original (tool ausente). Pode ser: (a) limitação do qwen2.5:7b, (b) prompt do write_file, (c) step ambíguo.

**Condição de abertura:** re-run com `DEFAULT_MODEL=anthropic:claude-haiku-4-5` após 2026-06-01. Se write-test também falhar com Anthropic → abre. Se passar → fecha automaticamente (era limitação do qwen2.5:7b).

**Prioridade:** BAIXA (condicional). Não bloqueia nenhuma outra fase.

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

## D.6 — Skills perms [done] (2026-05-30)
- /api/v1/skills volta a responder 200 (era 404 na D.5)
- Falha de perm agora gritante no log
- TODO D.6.1: remover hardcode do docker-config.yaml no Dockerfile
- Replay F9 fica para D.5 re-replay (depende de quota LLM)

---

## D.5 — Re-validação F5–F13 em runtime real ⭐ CANDIDATO PRÓXIMO

**Pendente da Fase A:** 10 fases marcadas TEÓRICAS (F5 Telegram, F6 Cron, F7 Critic, F8 Sandbox, F9 Voyager, F10 Deploy, F11 Web UI, F12 Channels, F13 LoRA).

Com D.1 em produção (tools corretas por step) + fix da Fase B (validação de execução real), agora é o momento natural de re-validar as fases TEÓRICAS. D.1 resolve o motivo arquitetural mais provável do TEATRO — agora os subagentes têm as ferramentas que precisam.

**Por que D.5 virou candidato natural agora:**
- D.1 em main: tools por step resolvidas dinamicamente
- Fase B em main: steps sem tool call → `failed_no_execution` (não mais silencioso)
- Próxima iteração pode revelar quantas fases "acordam" com D.1 ativo

**Proposta:** missão real por fase, em runtime, com critérios de aceite por DB count + efeito verificável. Re-escrever `AUDIT_REPORT.md` com status real após validação. Oportunidade de fechar também a limitação L3 do replay C10 (steps históricos reais).

**Prioridade:** MÉDIA → ALTA — pré-requisito para qualquer claim de "sistema pronto pra produção". Com D.1 em produção, D.5 é o próximo passo lógico antes de D.4 (Critic) ou D.2 (timeouts).
