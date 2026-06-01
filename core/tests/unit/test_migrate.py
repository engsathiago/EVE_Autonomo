"""Testes de apply_migrations — requer Postgres local (localhost:5432).

Skipa silenciosamente se o Postgres não estiver disponível.
"""

from __future__ import annotations

import os

import asyncpg
import pytest

_PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
_PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
_PG_USER = os.getenv("POSTGRES_USER", "agent")
_PG_PASS = os.getenv("POSTGRES_PASSWORD", "qualquercoisa123")
_PG_DB = os.getenv("POSTGRES_DB", "agent")
_DSN = f"postgresql://{_PG_USER}:{_PG_PASS}@{_PG_HOST}:{_PG_PORT}/{_PG_DB}"


def _pg_available() -> bool:
    import asyncio

    async def _check() -> bool:
        try:
            conn = await asyncpg.connect(_DSN, timeout=3)
            await conn.close()
            return True
        except Exception:
            return False

    return asyncio.run(_check())


_PG_UP = _pg_available()
pytestmark = pytest.mark.skipif(not _PG_UP, reason="postgres indisponível")


@pytest.mark.asyncio
async def test_dry_run_returns_list():
    """dry-run deve retornar lista de pendentes sem falhar."""
    from agent.db.migrate import apply_migrations

    result = await apply_migrations(_DSN, dry_run=True)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_stamp_all_idempotent():
    """stamp_all registra todas as migrations; segunda chamada retorna []."""
    from agent.db.migrate import stamp_all

    await stamp_all(_DSN)
    second = await stamp_all(_DSN)
    assert second == [], "segunda execução de stamp_all deve retornar lista vazia"


@pytest.mark.asyncio
async def test_apply_idempotent_after_stamp():
    """Após stamp, apply_migrations não aplica nada (tudo já marcado)."""
    from agent.db.migrate import apply_migrations, stamp_all

    await stamp_all(_DSN)
    pending = await apply_migrations(_DSN, dry_run=True)
    assert pending == [], "não deve haver pendentes após stamp_all"


@pytest.mark.asyncio
async def test_tracking_table_exists():
    """schema_migrations deve existir após qualquer chamada."""
    from agent.db.migrate import apply_migrations

    await apply_migrations(_DSN, dry_run=True)
    conn = await asyncpg.connect(_DSN)
    try:
        row = await conn.fetchrow(
            "SELECT to_regclass('public.schema_migrations') AS t"
        )
        assert row["t"] is not None, "tabela schema_migrations deve existir"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_applied_versions_non_empty():
    """Após stamp_all, a tabela deve ter pelo menos 1 registro."""
    from agent.db.migrate import stamp_all

    await stamp_all(_DSN)
    conn = await asyncpg.connect(_DSN)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
        assert count > 0, "deve haver pelo menos 1 migration registrada"
    finally:
        await conn.close()
