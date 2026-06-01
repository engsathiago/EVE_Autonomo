"""Testa MissionStore — validações de invariantes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.missions.store import MissionStore


def _make_pool() -> MagicMock:
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    return pool


def _make_mission_row(
    *,
    mission_id=None,
    status="active",
    parent_mission_id=None,
    success_criteria=None,
) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "id": mission_id or uuid4(),
        "title": "Missão teste",
        "objective": "Fazer algo verificável",
        "success_criteria": json.dumps(
            success_criteria or [{"criterion": "publicar 10 posts", "verifiable_via": "manual"}]
        ),
        "deadline": None,
        "status": status,
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
        "completed_at": None,
        "source": "cli",
        "source_ref": None,
        "parent_mission_id": parent_mission_id,
        "metadata": "{}",
    }[key]
    return row


@pytest.fixture
def store() -> MissionStore:
    return MissionStore(_make_pool())


@pytest.mark.asyncio
async def test_mission_create_requires_success_criteria(store: MissionStore) -> None:
    """Missão sem success_criteria deve falhar antes de tocar no DB."""
    with pytest.raises(ValueError, match="success_criteria"):
        await store.create(
            title="Missão inválida",
            objective="Objetivo sem critério",
            success_criteria=[],
            deadline=None,
            source="cli",
            source_ref=None,
        )
    store._pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_mission_step_sequence_unique(store: MissionStore) -> None:
    """Inserção de step com sequência duplicada propaga UniqueViolationError do DB."""
    import asyncpg

    mission_row = _make_mission_row()
    step_row = MagicMock()
    step_row.__getitem__ = lambda self, key: {
        "id": uuid4(),
        "mission_id": uuid4(),
        "sequence": 0,
        "description": "Passo inicial",
        "status": "pending",
        "task_id": None,
        "retry_count": 0,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }[key]

    # Primeiro add_step funciona; fetchrow retorna auto-seq=0
    store._pool.fetchrow = AsyncMock(
        side_effect=[
            MagicMock(**{"__getitem__": lambda self, k: 0}),  # next sequence
            step_row,
        ]
    )
    store._pool.execute = AsyncMock(side_effect=asyncpg.UniqueViolationError("duplicate key"))

    mission_id = uuid4()
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.add_step(mission_id, description="Step duplicado", sequence=0)


@pytest.mark.asyncio
async def test_child_mission_blocks_parent_status_transition(store: MissionStore) -> None:
    """Missão filha não pode ir para status terminal se pai ainda está ativo."""
    parent_id = uuid4()
    child_id = uuid4()

    parent_row = _make_mission_row(mission_id=parent_id, status="active")
    child_row = _make_mission_row(mission_id=child_id, status="active", parent_mission_id=parent_id)

    # get(child_id) → child_row; get(parent_id) → parent_row
    call_count = {"n": 0}

    async def fetchrow_side_effect(query, mission_id_arg):
        if mission_id_arg == child_id:
            return child_row
        return parent_row

    store._pool.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)

    with pytest.raises(ValueError, match="filha"):
        await store.update_status(child_id, "done")

    # Nenhum UPDATE deve ter sido chamado
    store._pool.execute.assert_not_called()
