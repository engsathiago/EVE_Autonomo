"""Fixtures compartilhados para testes de integração (requerem Postgres real)."""
from __future__ import annotations

import os

import asyncpg
import pytest_asyncio


@pytest_asyncio.fixture
async def db_pool() -> asyncpg.Pool:
    dsn = os.getenv("POSTGRES_DSN", "postgresql://agent:agent@postgres:5432/agent")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    yield pool
    await pool.close()
