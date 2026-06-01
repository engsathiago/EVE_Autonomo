"""
Reads mission reflections (F7) and skill executions (F9) from the database
and returns raw training-candidate records.

Does NOT format or filter for PII — that is DatasetBuilder's responsibility.
Applies only quality and time-window filters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from agent.observability.logger import get_logger

log = get_logger(__name__)


class TraceCollector:
    def __init__(
        self,
        pool: Any,  # asyncpg connection pool
        min_quality_score: float = 0.7,
        lookback_days: int = 30,
        exclude_skills: list[str] | None = None,
        max_dataset_size: int = 5000,
    ) -> None:
        self._pool = pool
        self._min_quality = min_quality_score
        self._lookback_days = lookback_days
        self._exclude_skills: set[str] = set(exclude_skills or [])
        self._max_dataset_size = max_dataset_size

    async def collect(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """
        Collects traces since `since` (or lookback_days ago if None).
        Returns list of raw dicts with origin metadata attached.
        """
        cutoff = since or (datetime.now(tz=UTC) - timedelta(days=self._lookback_days))
        log.info(
            "trace_collector.start",
            cutoff=cutoff.isoformat(),
            min_quality=self._min_quality,
        )

        mission_records = await self._collect_missions(cutoff)
        skill_records = await self._collect_skills(cutoff)

        all_records = mission_records + skill_records
        log.info(
            "trace_collector.done",
            missions=len(mission_records),
            skills=len(skill_records),
            total=len(all_records),
        )
        return all_records[: self._max_dataset_size]

    async def _collect_missions(self, cutoff: datetime) -> list[dict[str, Any]]:
        """
        Reads completed missions with successful reflections.
        Quality proxy: mission status = 'done', reflection has non-empty learned field.
        """
        query = """
            SELECT
                m.id            AS mission_id,
                m.title         AS mission_title,
                m.objective     AS objective,
                m.status        AS mission_status,
                r.delivered     AS delivered,
                r.learned       AS learned,
                r.quality_assessment AS quality_text,
                m.created_at    AS created_at
            FROM missions m
            JOIN mission_reflections r ON r.mission_id = m.id
            WHERE m.status = 'done'
              AND m.created_at >= $1
              AND LENGTH(r.learned) > 10
            ORDER BY m.created_at DESC
        """
        rows = await self._pool.fetch(query, cutoff)
        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "origin": {
                        "trace_id": f"mission:{row['mission_id']}",
                        "mission_id": str(row["mission_id"]),
                        "skill_id": None,
                        "type": "mission_reflection",
                    },
                    "input": row["objective"],
                    "output": row["delivered"],
                    "context": {
                        "title": row["mission_title"],
                        "learned": row["learned"],
                        "quality_text": row["quality_text"],
                    },
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        return records

    async def _collect_skills(self, cutoff: datetime) -> list[dict[str, Any]]:
        """
        Reads successful skill executions from F9.
        Quality proxy: success = true (skill executed without error).
        """
        query = """
            SELECT
                se.id           AS exec_id,
                se.skill_slug   AS skill_slug,
                se.mission_id   AS mission_id,
                se.input_json   AS input_json,
                se.output_json  AS output_json,
                se.duration_seconds AS duration_s,
                se.created_at   AS created_at
            FROM skill_executions se
            WHERE se.success = true
              AND se.created_at >= $1
              AND se.output_json IS NOT NULL
            ORDER BY se.created_at DESC
        """
        rows = await self._pool.fetch(query, cutoff)
        records: list[dict[str, Any]] = []
        for row in rows:
            if row["skill_slug"] in self._exclude_skills:
                continue

            try:
                input_data = json.loads(row["input_json"])
                output_data = json.loads(row["output_json"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Skip if input or output is trivially small
            input_str = json.dumps(input_data) if not isinstance(input_data, str) else input_data
            output_str = json.dumps(output_data) if not isinstance(output_data, str) else output_data
            if len(input_str) < 10 or len(output_str) < 10:
                continue

            records.append(
                {
                    "origin": {
                        "trace_id": f"skill:{row['exec_id']}",
                        "mission_id": row["mission_id"],
                        "skill_id": row["skill_slug"],
                        "type": "skill_execution",
                    },
                    "input": input_str,
                    "output": output_str,
                    "context": {
                        "skill_slug": row["skill_slug"],
                        "duration_s": float(row["duration_s"] or 0),
                    },
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        return records
