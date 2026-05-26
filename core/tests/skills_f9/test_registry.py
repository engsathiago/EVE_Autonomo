"""Testes do SkillRegistry F9 (C10: persistência + eventos)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.exceptions import SkillNotFound
from agent.skills.manifest import SkillManifestF9
from agent.skills.registry import SkillRegistry


def _fake_pool() -> MagicMock:
    pool = MagicMock()
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    return pool


def _manifest(slug: str = "test_skill") -> SkillManifestF9:
    return SkillManifestF9(
        slug=slug,
        version=1,
        created_at=datetime.now(tz=timezone.utc),
        description="test",
        embedding_text="test skill",
        inputs_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        outputs_schema={"type": "object", "properties": {"y": {"type": "string"}}, "required": ["y"]},
        sandbox_profile="SKILL_DEV",
        network_policy={"allow_domains": []},
    )


@pytest.mark.asyncio
async def test_save_calls_execute() -> None:
    pool = _fake_pool()
    reg = SkillRegistry(pool)
    manifest = _manifest()
    await reg.save(manifest, embedding=[0.1] * 384)
    pool.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_raises_not_found_when_missing() -> None:
    pool = _fake_pool()
    pool.fetchrow = AsyncMock(return_value=None)
    reg = SkillRegistry(pool)
    with pytest.raises(SkillNotFound):
        await reg.get("nonexistent")


@pytest.mark.asyncio
async def test_list_without_status_fetches_all() -> None:
    pool = _fake_pool()
    pool.fetch = AsyncMock(return_value=[])
    reg = SkillRegistry(pool)
    result = await reg.list()
    assert result == []
    pool.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_with_status_filters() -> None:
    pool = _fake_pool()
    pool.fetch = AsyncMock(return_value=[])
    reg = SkillRegistry(pool)
    await reg.list(status="active")
    call_args = pool.fetch.call_args[0]
    assert "status = $1" in call_args[0]


@pytest.mark.asyncio
async def test_update_status_calls_execute() -> None:
    pool = _fake_pool()
    reg = SkillRegistry(pool)
    await reg.update_status("my_slug", "active")
    pool.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_execution_inserts_and_updates_stats() -> None:
    pool = _fake_pool()
    reg = SkillRegistry(pool)
    exec_id = await reg.record_execution(
        "my_slug",
        success=True,
        duration_seconds=1.5,
        input_data={"x": "val"},
        output_data={"y": "out"},
    )
    assert isinstance(exec_id, str) and len(exec_id) == 32
    # INSERT into skill_executions + UPDATE skills
    assert pool.execute.await_count == 2


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_skills() -> None:
    pool = _fake_pool()
    pool.fetch = AsyncMock(return_value=[])
    reg = SkillRegistry(pool)
    result = await reg.search([0.1] * 384)
    assert result == []


@pytest.mark.asyncio
async def test_save_candidate_returns_id() -> None:
    pool = _fake_pool()
    reg = SkillRegistry(pool)
    cid = await reg.save_candidate("my_slug", ["exec1", "exec2"], 0.9)
    assert isinstance(cid, str) and len(cid) == 32
    pool.execute.assert_awaited_once()
