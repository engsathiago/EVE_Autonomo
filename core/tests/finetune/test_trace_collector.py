"""Tests for trace_collector.py — C2 (mission + skill queries, filters)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from agent.finetune.trace_collector import TraceCollector


def _make_mission_row(
    mission_id: str = "m1",
    objective: str = "solve the problem carefully",
    delivered: str = "here is the full solution",
    learned: str = "important lesson about efficiency",
    days_ago: int = 5,
) -> dict:
    created_at = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return {
        "mission_id": mission_id,
        "mission_title": f"Mission {mission_id}",
        "objective": objective,
        "mission_status": "done",
        "delivered": delivered,
        "learned": learned,
        "quality_text": "good",
        "created_at": created_at,
    }


def _make_skill_row(
    exec_id: str = "s1",
    skill_slug: str = "summarize_text",
    input_json: str | None = None,
    output_json: str | None = None,
    days_ago: int = 3,
) -> dict:
    created_at = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return {
        "exec_id": exec_id,
        "skill_slug": skill_slug,
        "mission_id": None,
        "input_json": input_json or json.dumps("explain this concept in detail"),
        "output_json": output_json or json.dumps("here is the detailed explanation of the concept"),
        "duration_s": 1.5,
        "created_at": created_at,
    }


class TestTraceCollectorCollect:
    @pytest.mark.asyncio
    async def test_returns_combined_missions_and_skills(self):
        pool = AsyncMock()
        mission_row = _make_mission_row()
        skill_row = _make_skill_row()
        pool.fetch.side_effect = [[mission_row], [skill_row]]

        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        assert len(records) == 2
        types = {r["origin"]["type"] for r in records}
        assert "mission_reflection" in types
        assert "skill_execution" in types

    @pytest.mark.asyncio
    async def test_caps_results_at_max_dataset_size(self):
        pool = AsyncMock()
        mission_rows = [_make_mission_row(mission_id=f"m{i}") for i in range(80)]
        skill_rows = [_make_skill_row(exec_id=f"s{i}", skill_slug="cls") for i in range(80)]
        pool.fetch.side_effect = [mission_rows, skill_rows]

        collector = TraceCollector(pool=pool, max_dataset_size=50)
        records = await collector.collect()

        assert len(records) == 50

    @pytest.mark.asyncio
    async def test_empty_pool_returns_empty_list(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [[], []]

        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        assert records == []

    @pytest.mark.asyncio
    async def test_passes_cutoff_to_db_query(self):
        """The query receives the correct cutoff datetime."""
        pool = AsyncMock()
        pool.fetch.side_effect = [[], []]

        explicit_since = datetime(2026, 1, 1, tzinfo=UTC)
        collector = TraceCollector(pool=pool, lookback_days=30)
        await collector.collect(since=explicit_since)

        # Both calls to pool.fetch should have received the cutoff
        assert pool.fetch.call_count == 2
        first_call_args = pool.fetch.call_args_list[0][0]
        assert explicit_since in first_call_args


class TestCollectMissions:
    @pytest.mark.asyncio
    async def test_mission_record_has_correct_origin(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [_make_mission_row(mission_id="abc123")],
            [],
        ]
        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        mission_records = [r for r in records if r["origin"]["type"] == "mission_reflection"]
        assert len(mission_records) == 1
        origin = mission_records[0]["origin"]
        assert origin["trace_id"] == "mission:abc123"
        assert origin["mission_id"] == "abc123"
        assert origin["skill_id"] is None

    @pytest.mark.asyncio
    async def test_mission_input_is_objective(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [_make_mission_row(objective="Find a solution to the problem")],
            [],
        ]
        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        mission_records = [r for r in records if r["origin"]["type"] == "mission_reflection"]
        assert mission_records[0]["input"] == "Find a solution to the problem"

    @pytest.mark.asyncio
    async def test_mission_output_is_delivered(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [_make_mission_row(delivered="The final delivered result")],
            [],
        ]
        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        mission_records = [r for r in records if r["origin"]["type"] == "mission_reflection"]
        assert mission_records[0]["output"] == "The final delivered result"


class TestCollectSkills:
    @pytest.mark.asyncio
    async def test_skill_record_has_correct_origin(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [],
            [_make_skill_row(exec_id="exec999", skill_slug="classify_intent")],
        ]
        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        skill_records = [r for r in records if r["origin"]["type"] == "skill_execution"]
        assert len(skill_records) == 1
        origin = skill_records[0]["origin"]
        assert origin["trace_id"] == "skill:exec999"
        assert origin["skill_id"] == "classify_intent"

    @pytest.mark.asyncio
    async def test_exclude_skills_filters_out_matching_slugs(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [],
            [
                _make_skill_row(exec_id="s1", skill_slug="summarize_text"),
                _make_skill_row(exec_id="s2", skill_slug="mock_send_email"),
                _make_skill_row(exec_id="s3", skill_slug="classify_intent"),
            ],
        ]
        collector = TraceCollector(pool=pool, exclude_skills=["mock_send_email"])
        records = await collector.collect()

        slugs = [r["origin"]["skill_id"] for r in records]
        assert "mock_send_email" not in slugs
        assert "summarize_text" in slugs
        assert "classify_intent" in slugs

    @pytest.mark.asyncio
    async def test_skips_records_with_trivially_small_output(self):
        pool = AsyncMock()
        pool.fetch.side_effect = [
            [],
            [
                _make_skill_row(exec_id="tiny", input_json=json.dumps("x"), output_json=json.dumps("y")),
                _make_skill_row(exec_id="ok", skill_slug="cls"),
            ],
        ]
        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        # tiny record should be skipped (< 10 chars input or output)
        exec_ids = [r["origin"]["trace_id"] for r in records]
        assert "skill:tiny" not in exec_ids
        assert "skill:ok" in exec_ids

    @pytest.mark.asyncio
    async def test_skips_records_with_invalid_json(self):
        pool = AsyncMock()
        bad_row = _make_skill_row(exec_id="bad_json")
        bad_row["input_json"] = "not valid json {{{"
        pool.fetch.side_effect = [[], [bad_row, _make_skill_row(exec_id="ok")]]

        collector = TraceCollector(pool=pool)
        records = await collector.collect()

        exec_ids = [r["origin"]["trace_id"] for r in records]
        assert "skill:bad_json" not in exec_ids
        assert "skill:ok" in exec_ids
