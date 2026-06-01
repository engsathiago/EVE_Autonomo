"""Testa CronStore — CRUD básico com pool mockado."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.scheduler.store import CronStore


def _make_pool() -> MagicMock:
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    return pool


@pytest.fixture
def store() -> CronStore:
    return CronStore(_make_pool())


@pytest.mark.asyncio
async def test_create_executes_insert(store: CronStore) -> None:
    store._pool.execute = AsyncMock()
    job = await store.create(
        name="test job",
        cron_expr="0 9 * * 1",
        task_tpl="fazer algo",
        source="telegram",
        target="123456",
        next_run=datetime.now(tz=UTC),
    )
    assert store._pool.execute.called
    assert job.name == "test job"
    assert job.cron_expr == "0 9 * * 1"


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found(store: CronStore) -> None:
    store._pool.fetchrow = AsyncMock(return_value=None)
    result = await store.get(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_enabled_only(store: CronStore) -> None:
    store._pool.fetch = AsyncMock(return_value=[])
    await store.list(enabled_only=True)
    call_args = store._pool.fetch.call_args
    assert "enabled = TRUE" in call_args[0][0]


@pytest.mark.asyncio
async def test_set_enabled_returns_true_on_update(store: CronStore) -> None:
    store._pool.execute = AsyncMock(return_value="UPDATE 1")
    result = await store.set_enabled(uuid4(), True)
    assert result is True


@pytest.mark.asyncio
async def test_set_enabled_returns_false_when_not_found(store: CronStore) -> None:
    store._pool.execute = AsyncMock(return_value="UPDATE 0")
    result = await store.set_enabled(uuid4(), False)
    assert result is False


@pytest.mark.asyncio
async def test_delete_returns_true_on_delete(store: CronStore) -> None:
    store._pool.execute = AsyncMock(return_value="DELETE 1")
    result = await store.delete(uuid4())
    assert result is True
