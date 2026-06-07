# Runtime Testing Guide

Guia do padrão de runtime validation estabelecido na Sub-fase C do Sprint 2.
Aplica-se a todas as fases a partir de F14+.

---

## Por que existe

Testes mockados passam. Runtime real quebra.

A auditoria de maio/2026 revelou que 14 fases de desenvolvimento tinham "1158 testes passando" mas a maioria mocava o banco, mocava o Redis, mocava o LLM. Quando tentamos exercitar os componentes contra Postgres real:

- `ApprovalManager.create()` quebrava com `DataError` — asyncpg não serializa `dict` para `jsonb` automaticamente
- Endpoint `POST /api/ui/chat` não existia — o chat só funciona via WebSocket
- `critic_evaluations` não persistiam em subagentes porque `db_pool` não era propagado

Nenhum teste unitário detectou nenhum desses bugs. Só o runtime detectou.

**Regra:** toda fase nova precisa de pelo menos um teste runtime que exercite o caminho crítico contra Postgres real antes de ser marcada como ✅ validada.

---

## Marker `runtime`

No `pyproject.toml` do `core/`:

```toml
[tool.pytest.ini_options]
markers = [
    "runtime: testes que requerem Postgres e Redis reais (excluídos do CI padrão)",
    "integration: testes de integração com serviços externos",
]
```

Para excluir do CI (que não tem infra real):

```toml
addopts = "-m 'not runtime and not integration'"
```

Para rodar localmente:

```bash
PYTHONPATH=src core/.venv312/bin/python -m pytest -m runtime tests/runtime/ -v
```

---

## Fixture asyncpg pattern

```python
# tests/runtime/conftest.py
import os
import asyncio
import asyncpg
import pytest

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def pg_pool():
    dsn = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://agent:agent@localhost:5432/agent_test"
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    yield pool
    await pool.close()
```

---

## A regra de ouro: asyncpg + jsonb

asyncpg **não serializa automaticamente** `dict` Python para `jsonb`. Você precisa fazer isso explicitamente.

### Escrita (INSERT / UPDATE)

```python
import json

await conn.execute(
    "INSERT INTO pending_approvals (skill_args, channel_ref) VALUES ($1, $2)",
    json.dumps(skill_args),   # dict → str JSON
    json.dumps(channel_ref),  # dict → str JSON
)
```

### Leitura (SELECT)

```python
row = await conn.fetchrow("SELECT skill_args, channel_ref FROM pending_approvals WHERE id = $1", id)

skill_args = json.loads(row["skill_args"]) if isinstance(row["skill_args"], str) else row["skill_args"]
```

### UUID

asyncpg retorna `uuid.UUID` como objeto Python, não como `str`. Se você precisa de string:

```python
approval_id = str(row["id"])   # uuid.UUID → str
```

Nunca chame `ApprovalState(id=row["id"], ...)` direto — Pydantic vai rejeitar `uuid.UUID` em campo `str`.

---

## Estrutura de arquivos

```
tests/
└── runtime/
    ├── conftest.py                         # fixtures asyncpg + event_loop
    ├── test_phase_5_approvals_real.py      # F5: ApprovalManager contra Postgres real
    ├── test_phase_6_cron_real.py           # F6: APScheduler + SubagentPool
    ├── test_phase_7_critic_real.py         # F7: Critic + MissionStore + pgvector
    ├── test_phase_8_sandbox_real.py        # F8: exec_tool subprocess + docker
    ├── test_phase_9_skills_real.py         # F9: SkillSynthesizer + embeddings reais
    ├── test_phase_11_webui_real.py         # F11: WebSocket + auth token
    └── evidence/
        ├── f5_approval_id.txt              # ID do approval criado no último run
        ├── f6_cron_job_id.txt              # ID do cron job criado
        ├── f7_critic_eval_id.txt           # ID da avaliação Critic
        ├── f8_sandbox_exec_id.txt          # ID da execução sandbox
        ├── f9_skill_execution_id.txt       # ID da skill executada
        └── f11_web_session_id.txt          # ID da session WebSocket
```

Os arquivos em `evidence/` são sobrescritos a cada run e servem como prova auditável de que o teste passou contra um banco real (não mock). Eles estão no `.gitignore` e **não são commitados** — pertencem ao runtime local.

---

## Template de teste runtime

```python
# tests/runtime/test_phase_XX_nome_real.py
import pytest
import json
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent / "evidence"

@pytest.mark.runtime
@pytest.mark.asyncio
async def test_create_and_retrieve_XX(pg_pool):
    """
    Testa criação e recuperação de XX contra Postgres real.
    Grava evidence/fXX_artifact_id.txt ao final.
    """
    async with pg_pool.acquire() as conn:
        # 1. Criação
        row = await conn.fetchrow(
            "INSERT INTO tabela (campo_jsonb) VALUES ($1) RETURNING id",
            json.dumps({"key": "value"}),
        )
        artifact_id = str(row["id"])

        # 2. Recuperação
        row2 = await conn.fetchrow(
            "SELECT campo_jsonb FROM tabela WHERE id = $1", row["id"]
        )
        data = json.loads(row2["campo_jsonb"])
        assert data["key"] == "value"

        # 3. Evidence
        EVIDENCE_DIR.mkdir(exist_ok=True)
        (EVIDENCE_DIR / "fXX_artifact_id.txt").write_text(artifact_id)
```

---

## Como NÃO escrever

```python
# ❌ NÃO: mockar Postgres
@patch("agent.core.db.pool.acquire")
async def test_create(mock_acquire):
    ...

# ❌ NÃO: mockar o ApprovalManager inteiro
with patch("agent.approvals.ApprovalManager") as mock_am:
    mock_am.create.return_value = ApprovalState(...)

# ❌ NÃO: chamar LLM real em testes runtime
# (isso torna o teste lento, flaky e caro)
async def test_critic_real():
    result = await critic.evaluate(...)  # não, LLM real não
```

Testes runtime validam **persistência** e **serialização** contra o banco real. A lógica de negócio (incluindo chamadas LLM) já é coberta pelos testes unitários com mocks.

---

## Checklist antes de marcar uma fase como ✅ validada

- [ ] Existe pelo menos um arquivo `tests/runtime/test_phase_N_*_real.py`
- [ ] O teste usa `@pytest.mark.runtime` e `@pytest.mark.asyncio`
- [ ] O teste exercita o caminho crítico de persistência (INSERT + SELECT) contra Postgres real
- [ ] Campos `jsonb` usam `json.dumps` na escrita e `json.loads` na leitura
- [ ] UUIDs são convertidos para `str` antes de passar para Pydantic
- [ ] O teste grava um arquivo em `tests/runtime/evidence/`
- [ ] O teste passa localmente com `pytest -m runtime tests/runtime/ -v`
- [ ] O marker `runtime` está no `pyproject.toml` e excluído do CI padrão

---

## Rodando em CI (opcional)

Se quiser CI com Postgres real, adicione um job separado no GitHub Actions:

```yaml
jobs:
  runtime-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: agent
          POSTGRES_PASSWORD: agent
          POSTGRES_DB: agent_test
        ports:
          - 5432:5432
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e "core[dev]"
      - run: agent db migrate
        env:
          DATABASE_URL: postgresql://agent:agent@localhost:5432/agent_test
      - run: pytest -m runtime tests/runtime/ -v
        env:
          TEST_DATABASE_URL: postgresql://agent:agent@localhost:5432/agent_test
```

Mantenha esse job separado do CI principal para não bloquear PRs por falha de infra.
