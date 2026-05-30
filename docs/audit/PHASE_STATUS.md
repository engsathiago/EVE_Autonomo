# Status das Fases — verdade auditada

> Fonte primária: [`EXECUTION_AUDIT.md`](EXECUTION_AUDIT.md) (queries diretas contra o banco em 2026-05-25)
> Critérios:
> - **VALIDADA** — evidência positiva de execução real com efeito verificável no banco ou em runtime
> - **PARCIAL** — alguma execução real, mas funcionalidade central não exercitada ou com defeito
> - **TEÓRICA** — código existe, testes unitários passam (mockados), nunca rodou em runtime real
> - **CONCLUÍDA** — fase de manutenção/auditoria (não é feature), entregue
> - **EM ANDAMENTO** — trabalho em progresso, sem tag final
> - **NÃO INICIADA** — no backlog, nenhum código comprometido

---

## Fases principais (F0–F13)

| Fase | Tag | Status | Evidência | Notas |
|------|-----|--------|-----------|-------|
| **F0** — Fundação (Docker, Postgres, Redis) | — | **VALIDADA** | Implícito: stack sobe, 516 model_invocations registradas | Sem tag explícita; pré-requisito funcional |
| **F1** — Core mínimo (AIAgent, loop ReAct) | — | **VALIDADA** | 516 model_invocations — LLM core chamado com sucesso | Fundação do loop confirmada |
| **F2** — Memória (MemoryStore, Curator, ContextCompressor) | — | **PARCIAL** | 15 memórias no banco; 12/15 são a mesma frase duplicada | Curator funciona mas sem deduplicação efetiva |
| **F3** — Skills builtin (SkillManager, SkillRunner, SkillCreator) | — | **PARCIAL** | 4 skill_invocations: 2 `summarize_text` (sucesso), 2 `web_research` (falha) | Skills YAML carregam e rodam; SkillCreator (criação dinâmica) nunca exercitado |
| **F4** — Multi-modelo (ModelRouter, Transports) | `phase-4-done` | **VALIDADA** | 5 modelos, 3 providers (Anthropic, Ollama), 516 chamadas | Fallback chain, capability check — funcionais |
| **F5** — Gateway Node + Telegram (Approvals) | — | **TEÓRICA** | `pending_approvals=0`, `outbound_messages_log=0` | Gateway pode ter subido, mas nunca gerou mensagem ou approval real |
| **F6** — Cron + Subagentes | `phase-6-done` | **TEÓRICA** | 5 subagent_runs todos TEATRO; 1 cron com `last_status=failed` | Subagentes instanciados mas retornam apenas prosa — nenhuma tool call real |
| **F7** — Missões + Crítico Autônomo | `phase-7-done` | **TEÓRICA** | 2 missões, ambas TEATRO; 9 `critic_evaluations` sem `mission_id`/`task_id` | Executor marcava steps `done` sem validar tool calls (bug corrigido na Fase B) |
| **F8** — Sandboxes (SubprocessSandbox, DockerSandbox) | `phase-8-done` | **TEÓRICA** | `sandbox_executions=0` | `exec_tool` nunca foi acionado em runtime real |
| **F9** — Skills Voyager (SkillSynthesizer, SkillRegistry, SkillDecayManager) | `phase-9-done` | **TEÓRICA** | `skills=0 rows`, `skill_candidates=0`, `skill_executions=0` | Nenhuma skill foi sintetizada, registrada ou executada via pipeline Voyager |
| **F10** — Deploy VPS (Supervisor, Workers, systemd) | `phase-10-done` | **TEÓRICA** | `deploy_events=0`, `worker_health=0 rows` | Supervisor nunca arrancou workers em runtime real |
| **F11** — Web UI (8 painéis, WebSocket multiplexado) | `phase-11-done` | **TEÓRICA** | `web_sessions=0` | UI pode existir; nunca foi acessada (nenhuma sessão registrada) |
| **F12** — Canais extras (Discord, Slack, Email) | `phase-12-done` | **TEÓRICA** | `channel_messages=0` | Adaptadores têm código, nunca receberam ou enviaram mensagem real |
| **F13** — Fine-tuning LoRA periódico | `phase-13-done` | **TEÓRICA** | `finetune_runs=0`, `benchmark_results=0` | LoraTrainer nunca executado; benchmark gates nunca avaliados |

---

## Fases de manutenção e melhorias (Fase A, B, C, D.x)

| Fase | Tag | Status | Evidência | Notas |
|------|-----|--------|-----------|-------|
| **Fase A** — Auditoria de execução real | — | **CONCLUÍDA** | `docs/audit/EXECUTION_AUDIT.md` gerado | Queries diretas ao banco em 2026-05-25; revelou 10 fases TEÓRICAS |
| **Fase B** — Fix do executor (validação de execução) | `fase-b-done` | **CONCLUÍDA** | `failed_no_execution` em vez de `done` falso; suite 100% verde | `ToolCallSummary`, `analyze_turn`, migration 015 |
| **Fase C** — Deploy controlado na VPS | — | **PULADA** | — | Decidido não entrar no roadmap público; VPS mantida separadamente |
| **D.1** — Tool routing por step | `d1-done` | **VALIDADA** | Replay C10: 4/5 execuções TEATRO→executed com Ollama | `resolve_tools_for_step()`, migration 016; mergeado em main 2026-05-28 |
| **D1-FU-1** — write_file prose_only (condicional) | — | **CONDICIONAL** | — | Só abre se Anthropic também falhar no re-run pós 2026-06-01 |
| **D.2** — Timeout adaptativo por modelo | — | **NÃO INICIADA** | — | qwen3:30b >60s → prosa por timeout; ver `pool.py` |
| **D.3** — FK violation em model_invocations | — | **NÃO INICIADA** | — | session_id sem conversa parent gera warning; ver `router.py:271` |
| **D.4** — Critic conectado ao mission flow | — | **NÃO INICIADA** | — | 9 `critic_evaluations` órfãs; hook em `_execute_tools` necessário |
| **D.5** — Re-validação F5–F13 em runtime real | — | **NÃO INICIADA** | — | Candidato natural pós D.1 + Fase B; pré-requisito para "pronto para produção" |
| **D.6** — Skills permissions + router wired | — | **EM ANDAMENTO** | `feature/d6-skills-perms`, 4 commits além do main | `skills_dir` configurável, `SkillsRouter` wired |
| **D.7** — (a definir) | — | **NÃO INICIADA** | — | |

---

## Resumo executivo

| Categoria | Fases | % |
|-----------|-------|---|
| VALIDADA (execução real confirmada) | F0, F1, F4, D.1 | ~14% |
| PARCIAL (alguma execução, mas incompleta) | F2, F3 | ~14% |
| TEÓRICA (código + testes mockados, sem runtime) | F5–F13 | ~64% |
| CONCLUÍDA / EM ANDAMENTO (manutenção) | Fase A, B, D.6 | — |

> **Nota:** "testes passando" ≠ "fase entregue".
> O critério mínimo de validação é ao menos 1 execução real com efeito verificável persistido no banco.
> Ver `docs/known-issues.md` para issues conhecidos não corrigidos.
