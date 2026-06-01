"""Testa ReflexiveMemory — decay e times_recalled."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.memory.reflexive import ReflexiveMemory


def _make_pool() -> MagicMock:
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    return pool


def _make_insight_row(
    *,
    insight_id=None,
    forgotten=False,
    times_recalled=0,
    relevance_score=0.5,
) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": insight_id or uuid4(),
        "insight": "Missões de conteúdo precisam de 7 dias de buffer",
        "source_mission_id": None,
        "relevance_score": relevance_score,
        "forgotten": forgotten,
        "times_recalled": times_recalled,
        "last_recalled_at": None,
        "created_at": datetime.now(tz=UTC),
    }[key]
    return row


@pytest.fixture
def memory() -> ReflexiveMemory:
    return ReflexiveMemory(_make_pool())


@pytest.mark.asyncio
async def test_reflexive_memory_decay_marks_forgotten_not_deleted(memory: ReflexiveMemory) -> None:
    """Decay deve chamar UPDATE (marcar forgotten=TRUE), nunca DELETE."""
    memory._pool.execute = AsyncMock(return_value="UPDATE 3")

    count = await memory.decay()

    assert count == 3
    call_args = memory._pool.execute.call_args[0][0]
    assert "UPDATE" in call_args.upper()
    assert "DELETE" not in call_args.upper()
    assert "forgotten" in call_args.lower()


@pytest.mark.asyncio
async def test_recall_increments_times_recalled(memory: ReflexiveMemory) -> None:
    """recall() deve incrementar times_recalled para cada resultado retornado."""
    insight_id = uuid4()
    row = _make_insight_row(insight_id=insight_id, times_recalled=2)

    memory._pool.fetch = AsyncMock(return_value=[row])
    memory._pool.execute = AsyncMock()

    with patch("agent.memory.reflexive.embed", AsyncMock(return_value=[0.1] * 384)):
        results = await memory.recall("buffer de conteúdo", top_k=3)

    assert len(results) == 1
    assert results[0].times_recalled == 2

    # Verifica que execute foi chamado para incrementar times_recalled
    execute_calls = [str(c) for c in memory._pool.execute.call_args_list]
    assert any("times_recalled" in c for c in execute_calls)
