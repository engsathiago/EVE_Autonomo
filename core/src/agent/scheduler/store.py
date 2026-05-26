from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from agent.observability.logger import get_logger

log = get_logger(__name__)


class CronJob:
    def __init__(
        self,
        *,
        id: UUID,
        name: str,
        cron_expr: str,
        task_tpl: str,
        source: str,
        nl_original: str | None = None,
        target: str | None = None,
        enabled: bool = True,
        last_run: datetime | None = None,
        next_run: datetime | None = None,
        last_status: str | None = None,
        last_error: str | None = None,
        metadata: dict | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.cron_expr = cron_expr
        self.nl_original = nl_original
        self.task_tpl = task_tpl
        self.source = source
        self.target = target
        self.enabled = enabled
        self.last_run = last_run
        self.next_run = next_run
        self.last_status = last_status
        self.last_error = last_error
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()


class CronStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        name: str,
        cron_expr: str,
        task_tpl: str,
        source: str,
        nl_original: str | None = None,
        target: str | None = None,
        next_run: datetime | None = None,
        metadata: dict | None = None,
    ) -> CronJob:
        job_id = uuid4()
        now = datetime.utcnow()
        await self._pool.execute(
            """
            INSERT INTO cron_jobs
                (id, name, cron_expr, nl_original, task_tpl, source, target,
                 next_run, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
            """,
            job_id,
            name,
            cron_expr,
            nl_original,
            task_tpl,
            source,
            target,
            next_run,
            json.dumps(metadata or {}, ensure_ascii=False),
            now,
            now,
        )
        return CronJob(
            id=job_id,
            name=name,
            cron_expr=cron_expr,
            nl_original=nl_original,
            task_tpl=task_tpl,
            source=source,
            target=target,
            next_run=next_run,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )

    async def get(self, job_id: UUID) -> CronJob | None:
        row = await self._pool.fetchrow("SELECT * FROM cron_jobs WHERE id = $1", job_id)
        return _row_to_job(row) if row else None

    async def list(self, enabled_only: bool = False) -> list[CronJob]:
        if enabled_only:
            rows = await self._pool.fetch(
                "SELECT * FROM cron_jobs WHERE enabled = TRUE ORDER BY created_at DESC"
            )
        else:
            rows = await self._pool.fetch("SELECT * FROM cron_jobs ORDER BY created_at DESC")
        return [_row_to_job(r) for r in rows]

    async def set_enabled(self, job_id: UUID, enabled: bool) -> bool:
        result = await self._pool.execute(
            "UPDATE cron_jobs SET enabled = $2, updated_at = NOW() WHERE id = $1",
            job_id,
            enabled,
        )
        return result == "UPDATE 1"

    async def update_run(
        self,
        job_id: UUID,
        *,
        last_run: datetime,
        next_run: datetime | None,
        last_status: str,
        last_error: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE cron_jobs
               SET last_run    = $2,
                   next_run    = $3,
                   last_status = $4,
                   last_error  = $5,
                   updated_at  = NOW()
             WHERE id = $1
            """,
            job_id,
            last_run,
            next_run,
            last_status,
            last_error,
        )

    async def delete(self, job_id: UUID) -> bool:
        result = await self._pool.execute("DELETE FROM cron_jobs WHERE id = $1", job_id)
        return result == "DELETE 1"


def _row_to_job(row: asyncpg.Record) -> CronJob:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return CronJob(
        id=row["id"],
        name=row["name"],
        cron_expr=row["cron_expr"],
        nl_original=row["nl_original"],
        task_tpl=row["task_tpl"],
        source=row["source"],
        target=row["target"],
        enabled=row["enabled"],
        last_run=row["last_run"],
        next_run=row["next_run"],
        last_status=row["last_status"],
        last_error=row["last_error"],
        metadata=meta or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
