"""Verifica que `agent db migrate` sobe schema completo em banco virgem.

Skipa silenciosamente se o Postgres não estiver disponível.

Cobre A.4 do PLAN.md: confirma que a ausência de migration 001 não é um
gap — o runner aplica 002+ sem erro e cria todas as tabelas esperadas.
"""

from __future__ import annotations

import os
import uuid

import asyncpg
import pytest

_PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
_PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
_PG_USER = os.getenv("POSTGRES_USER", "agent")
_PG_PASS = os.getenv("POSTGRES_PASSWORD", "qualquercoisa123")
_PG_ADMIN_DB = os.getenv("POSTGRES_DB", "agent")

# Banco temporário isolado para cada execução de teste
_TMP_DB = f"agent_test_fresh_{uuid.uuid4().hex[:8]}"
_DSN_ADMIN = f"postgresql://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_PG_ADMIN_DB}"
_DSN_TMP = f"postgresql://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_TMP_DB}"


def _pg_available() -> bool:
    import asyncio

    async def _check() -> bool:
        try:
            conn = await asyncpg.connect(_DSN_ADMIN, timeout=3)
            await conn.close()
            return True
        except Exception:
            return False

    return asyncio.run(_check())


_PG_UP = _pg_available()
pytestmark = pytest.mark.skipif(not _PG_UP, reason="postgres indisponível")

# Tabelas obrigatórias que devem existir após `apply_migrations` em banco virgem.
# Cada uma pertence a uma migration diferente para cobrir a cadeia completa.
_EXPECTED_TABLES = [
    "conversations",       # 002
    "memories",            # 002
    "skill_invocations",   # 003
    "model_invocations",   # 004
    "pending_approvals",   # 005
    "cron_jobs",           # 007
    "missions",            # 008
    "sandbox_executions",  # 009
    "skills",              # 010
    "web_sessions",        # 012
]


@pytest.fixture(scope="module")
async def fresh_db():
    """Cria banco temporário, aplica migrations, yield DSN, dropa ao fim."""
    admin_conn = await asyncpg.connect(_DSN_ADMIN)
    try:
        await admin_conn.execute(f'CREATE DATABASE "{_TMP_DB}"')
    finally:
        await admin_conn.close()

    from agent.db.migrate import apply_migrations

    applied = await apply_migrations(_DSN_TMP)
    assert len(applied) > 0, "nenhuma migration foi aplicada — verifique MIGRATIONS_DIR"

    yield _DSN_TMP

    admin_conn = await asyncpg.connect(_DSN_ADMIN)
    try:
        await admin_conn.execute(f'DROP DATABASE IF EXISTS "{_TMP_DB}"')
    finally:
        await admin_conn.close()


@pytest.mark.asyncio
async def test_apply_migrations_starts_at_002(fresh_db):
    """apply_migrations aplica a partir de 002 sem erro em banco virgem."""
    conn = await asyncpg.connect(fresh_db)
    try:
        versions = [
            r["version"]
            for r in await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        ]
    finally:
        await conn.close()

    assert "002" in versions, "migration 002 deve estar registrada"
    assert "001" not in versions, "não deve haver migration 001 fictícia registrada"


@pytest.mark.asyncio
async def test_all_expected_tables_exist(fresh_db):
    """Todas as tabelas core devem existir após apply_migrations em banco virgem."""
    conn = await asyncpg.connect(fresh_db)
    try:
        missing = []
        for table in _EXPECTED_TABLES:
            row = await conn.fetchrow(
                "SELECT to_regclass($1::text) AS t", f"public.{table}"
            )
            if row["t"] is None:
                missing.append(table)
    finally:
        await conn.close()

    assert missing == [], f"tabelas ausentes após migrate: {missing}"


@pytest.mark.asyncio
async def test_schema_migrations_tracking_table(fresh_db):
    """schema_migrations deve existir e ter ao menos 1 registro."""
    conn = await asyncpg.connect(fresh_db)
    try:
        row = await conn.fetchrow("SELECT to_regclass('public.schema_migrations') AS t")
        assert row["t"] is not None, "tabela schema_migrations deve existir"

        count = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
        assert count > 0, "deve haver ao menos 1 migration registrada"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_second_run_is_idempotent(fresh_db):
    """Segunda chamada a apply_migrations não aplica nada (idempotência)."""
    from agent.db.migrate import apply_migrations

    second = await apply_migrations(fresh_db)
    assert second == [], "segunda execução não deve aplicar migrations"
