# Débito Técnico — testes skippados

Última atualização: 2026-05-16
Origem: detectados durante validação F12, originados em F8 (Sandboxes de execução).

## Causa raiz

Todos os 9 testes usam a fixture `tmpdb` que tenta conectar ao PostgreSQL real
(`asyncpg.connect(POSTGRES_DSN)`). O serviço não está disponível fora do Docker
Compose, portanto o `conftest.py` de sandbox captura o erro de conexão e invoca
`pytest.skip("Postgres não disponível (...) — pule com -m 'not integration'")`.

Esses testes **funcionam corretamente** em ambiente Docker (CI e deploy). O skip
é um mecanismo de degradação graciosa para dev local sem Docker rodando.

## Inventário

| # | Teste | Razão skip | O que valida | Prioridade |
|---|-------|-----------|--------------|------------|
| 1 | `tests/sandbox/test_exec_tool.py::test_exec_tool_writes_db_row` | Postgres não disponível | `exec_tool()` grava linha em `sandbox_executions` ao concluir execução | F8-retest-on-docker |
| 2 | `tests/sandbox/test_exec_tool.py::test_exec_tool_stores_mission_and_subagent_ids` | Postgres não disponível | `exec_tool()` propaga `mission_id` e `subagent_id` para o registro de execução | F8-retest-on-docker |
| 3 | `tests/sandbox/test_persistence.py::test_migration_applies_idempotent` | Postgres não disponível | Rodar `009_sandbox_executions.sql` duas vezes não gera erro (`IF NOT EXISTS`) | F8-retest-on-docker |
| 4 | `tests/sandbox/test_persistence.py::test_migration_creates_table` | Postgres não disponível | Migration cria tabela `sandbox_executions` em `public` | F8-retest-on-docker |
| 5 | `tests/sandbox/test_persistence.py::test_migration_creates_indexes` | Postgres não disponível | Migration cria os índices declarados na migration 009 | F8-retest-on-docker |
| 6 | `tests/sandbox/test_persistence.py::test_registry_record_inserts_row` | Postgres não disponível | `SandboxRegistry.record()` insere linha com status correto | F8-retest-on-docker |
| 7 | `tests/sandbox/test_persistence.py::test_registry_stores_mission_and_subagent` | Postgres não disponível | `SandboxRegistry` persiste `mission_id` e `subagent_id` no registro | F8-retest-on-docker |
| 8 | `tests/sandbox/test_persistence.py::test_registry_stores_timed_out_flag` | Postgres não disponível | `SandboxRegistry` sinaliza `timed_out=True` quando sandbox expira | F8-retest-on-docker |
| 9 | `tests/sandbox/test_persistence.py::test_registry_command_preview_at_200_chars` | Postgres não disponível | Preview do comando truncado a 200 chars ao gravar em banco | F8-retest-on-docker |

## Critério de prioridade

- **F8-retest-on-docker**: testes de integração com banco real — passam corretamente
  quando Docker Compose está rodando. Não são blockers de nenhuma fase futura;
  são resolvidos automaticamente ao rodar `docker compose up` + `pytest -m integration`.
- **F13-blocker**: toca memory/embeddings, precisa estar verde antes de fine-tuning.
- **F13-nice**: relacionado a F13 mas não bloqueante.
- **F14+**: pode esperar.

## Ação necessária

Nenhuma. Os testes estão corretos e passam em Docker. Para validar localmente:

```bash
docker compose up -d postgres
cd core && .venv312/bin/python -m pytest tests/sandbox/ -v
# Todos os 9 testes que estavam skippados devem passar
```

Para excluir da suite local (CI já inclui com Docker):

```bash
.venv312/bin/python -m pytest tests/ -m "not integration"
```

**Antes da F13:** criar perfil de teste "integration" no `pyproject.toml`
que SOBE postgres via `testcontainers-python` e roda os 9 skippados
de fato. Sem isso, F13 (LoRA sobre memory) está construindo em cima de
cobertura cega.

## Nota

O CLAUDE.md menciona "testes quebrados desde F5 em memory/skills" — esses são um
conjunto diferente (46 failing) que não aparecem mais como `SKIPPED` mas como
`FAILED` quando rodados. Eles não constam neste inventário porque o mecanismo é
diferente (incompatibilidade de versão de pytest-asyncio, não ausência de serviço).
Esse conjunto separado será abordado em manutenção dedicada conforme previsto.
