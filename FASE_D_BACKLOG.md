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

## D.5 — Re-validação F5–F13 em runtime real ✅ EXECUTADA (2026-05-29)

**Resultado:** 4/9 testáveis destrancadas. NOT_APPLICABLE: F13. NOT_APPLICABLE_INFRA: F11.

| Fase | Resultado | Evidência chave |
|------|-----------|-----------------|
| F5 (Telegram) | **DESTRANCOU** | `outbound.dispatched` no gateway log; bot entregou mensagem |
| F6 (Cron+Subagentes) | **DESTRANCOU** | `cron_jobs.last_status=ok`; `subagent_runs.tools_used={write_file}` |
| F7 (Missões+Critic) | AINDA TEÓRICA | Steps = prosa; `step_tool_routing=0`; `critic_evaluations=0` |
| F8 (Sandboxes) | **PARCIAL** | `noop_skill` em `/health/deep` ok=true via exec_tool+SubprocessSandbox; `sandbox_executions=0` |
| F9 (Skills Voyager) | AINDA TEÓRICA | PermissionError `/app/src/agent/skills/_active`; `/api/v1/skills` → 404 |
| F10 (Deploy) | **DESTRANCOU** | `/health/live`, `/health/ready`, `/health/deep` ativos |
| F11 (Web UI) | NOT_APPLICABLE_INFRA | `RuntimeError: Cannot add middleware after application started` |
| F12 (Canais) | AINDA TEÓRICA | Credenciais incompletas (DISCORD_GUILD_ID, SLACK_APP_TOKEN) |
| F13 (LoRA) | NOT_APPLICABLE | Sem checkpoint; sem GPU |

**Bugs de deployment corrigidos durante D.5:**
- `server.py:261`: `parents[4]` → `Path(settings.skills.skills_dir)` (IndexError no container)
- `server.py:268`: mkdir movido para dentro do try/except

**Relatório completo:** `docs/phases/D5_VALIDATION_RESULTS.md`  
**Branch:** `validate/d5-runtime-revalidation` (aguarda review e merge)

**Threshold não atingido (4 < 5) → sem tag d5-done. Próxima fase: D.4.**
