"""Testes do SkillDecayManager — C8: decay de skills inúteis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.skills.decay import SkillDecayManager, _days_since


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


def _make_registry(skills: list[dict], executions: list[dict] | None = None) -> MagicMock:
    registry = MagicMock()
    registry.list = AsyncMock(return_value=skills)
    registry.recent_executions = AsyncMock(return_value=executions or [])
    registry.update_status = AsyncMock()
    return registry


def _skill(slug: str = "s1", promoted_at: datetime | None = None, last_used: datetime | None = None) -> dict:
    return {
        "slug": slug,
        "version": 1,
        "promoted_at": promoted_at or _days_ago(10),
        "last_used_at": last_used,
        "executions_count": 0,
        "successes_count": 0,
        "failures_count": 0,
    }


@pytest.mark.asyncio
async def test_no_decay_for_recently_used(tmp_path: Path) -> None:
    skill = _skill("s1", last_used=_days_ago(5))
    registry = _make_registry([skill])
    manager = SkillDecayManager(registry, tmp_path / "active", tmp_path / "archive")
    counts = await manager.scan(now=_now())
    assert counts["deprecated"] == 0
    assert counts["flagged"] == 0


@pytest.mark.asyncio
async def test_deprecate_skill_unused_30_days(tmp_path: Path) -> None:
    """C8: skill sem uso em 30 dias → deprecated."""
    (tmp_path / "active" / "s1").mkdir(parents=True)
    skill = _skill("s1", promoted_at=_days_ago(40), last_used=_days_ago(31))
    registry = _make_registry([skill])
    manager = SkillDecayManager(registry, tmp_path / "active", tmp_path / "archive")

    with patch("agent.skills.decay._emit", new_callable=AsyncMock):
        counts = await manager.scan(now=_now())

    assert counts["deprecated"] == 1
    registry.update_status.assert_awaited_once_with("s1", "deprecated")


@pytest.mark.asyncio
async def test_flag_high_error_rate(tmp_path: Path) -> None:
    """C8: >40% erro nas últimas 10 execuções → flagged_for_review."""
    skill = _skill("s1", last_used=_days_ago(1))
    executions = [{"success": False, "duration_seconds": 1.0}] * 5 + [{"success": True, "duration_seconds": 1.0}] * 5
    registry = _make_registry([skill], executions=executions)
    manager = SkillDecayManager(registry, tmp_path / "active", tmp_path / "archive")

    with patch("agent.skills.decay._emit", new_callable=AsyncMock):
        counts = await manager.scan(now=_now())

    assert counts["flagged"] == 1
    registry.update_status.assert_awaited_once_with("s1", "flagged_for_review")


@pytest.mark.asyncio
async def test_mature_after_enough_successes(tmp_path: Path) -> None:
    """C8: version=1, ≥7 dias aprovada, ≥20 execuções bem-sucedidas → mature."""
    skill = {
        "slug": "s1",
        "version": 1,
        "promoted_at": _days_ago(10),
        "last_used_at": _days_ago(1),
        "executions_count": 25,
        "successes_count": 25,
        "failures_count": 0,
    }
    executions = [{"success": True, "duration_seconds": 0.5}] * 10
    registry = _make_registry([skill], executions=executions)
    manager = SkillDecayManager(registry, tmp_path / "active", tmp_path / "archive")

    with patch("agent.skills.decay._emit", new_callable=AsyncMock):
        counts = await manager.scan(now=_now())

    assert counts["matured"] == 1


@pytest.mark.asyncio
async def test_no_mature_with_insufficient_successes(tmp_path: Path) -> None:
    skill = {
        "slug": "s1",
        "version": 1,
        "promoted_at": _days_ago(10),
        "last_used_at": _days_ago(1),
        "executions_count": 5,
        "successes_count": 5,
        "failures_count": 0,
    }
    registry = _make_registry([skill])
    manager = SkillDecayManager(registry, tmp_path / "active", tmp_path / "archive")
    counts = await manager.scan(now=_now())
    assert counts["matured"] == 0


def test_days_since_string_datetime() -> None:
    dt = (_now() - timedelta(days=5)).isoformat()
    days = _days_since(dt, _now())
    assert 4.9 < days < 5.1


def test_days_since_naive_datetime() -> None:
    dt = datetime.now() - timedelta(days=3)
    days = _days_since(dt, _now())
    # Margem de 0.5 dia para timezone offset entre naive e aware
    assert 2.5 < days < 3.5
