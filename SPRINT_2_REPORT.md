# Sprint 2 + Sub-fase A — Fechamento

Data: 2026-06-06

## Sub-fases entregues

| Sub-fase | Branch | Descrição |
|---|---|---|
| A.4 | fix/migration-001 | Documenta ausência de migration 001 (não é gap) + teste de banco virgem |
| A.1 | merge/d4-critic-missions | Fix db_pool propagation em subagentes + Critic persiste mission_id |
| A.2 | merge/d5-validation | Fix skills_dir + docs D.5 runtime re-validation |
| B.1 | feature/ollama-cloud-transport | OllamaCloudTransport como provider separado `ollama_cloud` |
| B.2 | feature/ollama-cloud-default | DEFAULT_MODEL → `ollama_cloud:deepseek-v3.1:cloud` |
| B.3 | feature/ollama-cloud-unhardcode | TierClassifier/Critic/Planner/Reflector lendo de Settings (não hardcoded) |
| B.4 | (mesma branch B.3) | CLAUDE.md + OLLAMA_CLOUD.md atualizados para sprint-2 |
| A.3 | (mesma branch B.3) | Critic gate para skills irreversíveis em AIAgent._execute_tools |

## Tabela de evidência

| Sub-fase | Tabela / Artefato | Status |
|---|---|---|
| A.3 | `critic_evaluations.mission_id IS NOT NULL` | PENDENTE — integration test skipped sem Postgres local; fica para Sub-fase C (Postgres está em Docker) |
| A.4 | `schema_migrations` + `core/migrations/README.md` | OK — via suíte |
| A.1 | `subagent_runs` + db_pool propagado | OK — test_subagent_db_pool_propagation |
| A.2 | `skills_dir` em `SkillRunner` | OK — test_skills_dir_fix |
| B.1–B.3 | `config.py`, `router.py`, componentes | OK — 30 testes novos de config |

## Testes

| Marco | Contagem | Notas |
|---|---|---|
| Baseline main pré-Sprint 2 | 1157 passed | Antes de A.4 |
| Pós-Sprint 2 + Sub-fase A (main) | 1203 passed | Ignorando `test_supervisor_internals.py` (padrão) |
| Suíte passo 3 (ignora `supervisor_real`) | 1229 passed, 1 failed | +26 testes de `supervisor_internals.py` incluídos; 1 falha pré-existente (SQLite não suporta `IDENTITY` — sintaxe PostgreSQL) |
| Quebras introduzidas pelo Sprint 2 | 0 | — |
| Testes ajustados | 2 | `test_ollama_cloud.py` — acoplados ao hardcode `anthropic:` antigo, corretamente atualizados para `ollama_cloud:` |
| Testes novos | +46 | B.1: 12, B.2: 4, B.3: 12, A.3: 3 unit + 1 skipped |

## Itens descobertos/decididos no processo

- **Sistema usa `schema_migrations` custom, não Alembic** — numeração começa em 002, sem gap (A.4)
- **Repo tem dois venvs** (`.venv` incompleto, `.venv312` com deps completas) — TODO registrado em PLAN.md seção D.2
- **`from_yaml()` não parseava bloco `critic:` do YAML** — lacuna corrigida oportunamente em B.3
- **Migration 017** usa pattern `DROP CONSTRAINT + ADD CONSTRAINT` (única forma em Postgres para adicionar valor a CHECK constraint existente); idempotente via `schema_migrations`
- **`tool_router.py` tinha hardcode inline** `"anthropic:claude-haiku-4-5"` fora de componente nomeado — corrigido para `model_router.default_model()` em B.3
- **`_maybe_gate_tool`** já existia em core.py mas não cobria skills — A.3 fechou essa lacuna

## Docker (confirmado para Sub-fase C)

```
agent-core-1      Up 3 days (healthy)    :8000
agent-gateway-1   Up 3 days (unhealthy)  :3000
agent-redis-1     Up 3 days (healthy)    :6379
agent-postgres-1  Up 3 days (healthy)    :5432
```

Postgres disponível em `:5432` — habilita integration tests (incluindo `test_critic_persists_mission_id`).

## Pendências para próximas Sprints

- **Sub-fase C** (Runtime Validation F5/F6/F7/F8/F9/F11) — Docker confirmado ✅
- **Sub-fase D** (VPS rebuild) — depende de C concluída
- **Limpeza de venvs duplicados** — parte da D.2
- **Integration test A.3** (`test_critic_persists_mission_id`) — rodar contra Postgres do Docker
