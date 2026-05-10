from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import asyncpg

from agent.observability.logger import get_logger
from agent.tasks.task import Task, TaskSource, TaskStatus

log = get_logger(__name__)


class TaskStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, task: Task) -> Task:
        await self._pool.execute(
            """
            INSERT INTO tasks (id, parent_id, cron_job_id, source, content,
                               tier, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            task.id,
            task.parent_id,
            task.cron_job_id,
            str(task.source),
            task.content,
            task.tier,
            task.status.value,
            task.created_at,
        )
        return task

    async def update_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
        iterations: int | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        tier: str | None = None,
    ) -> None:
        now = datetime.utcnow()
        started_at = now if status == TaskStatus.RUNNING else None
        finished_at = now if status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.TIMEOUT) else None

        await self._pool.execute(
            """
            UPDATE tasks
               SET status      = $2,
                   result      = COALESCE($3::jsonb, result),
                   error       = COALESCE($4, error),
                   iterations  = COALESCE($5, iterations),
                   tokens_in   = COALESCE($6, tokens_in),
                   tokens_out  = COALESCE($7, tokens_out),
                   tier        = COALESCE($8, tier),
                   started_at  = COALESCE($9, started_at),
                   finished_at = COALESCE($10, finished_at)
             WHERE id = $1
            """,
            task_id,
            status.value,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            iterations,
            tokens_in,
            tokens_out,
            tier,
            started_at,
            finished_at,
        )

    async def get(self, task_id: UUID) -> Task | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM tasks WHERE id = $1", task_id
        )
        return _row_to_task(row) if row else None

    async def list_by_status(
        self, status: TaskStatus | None = None, limit: int = 50
    ) -> list[Task]:
        if status:
            rows = await self._pool.fetch(
                "SELECT * FROM tasks WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                status.value, limit,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT $1", limit
            )
        return [_row_to_task(r) for r in rows]

    async def get_tree(self, task_id: UUID) -> list[Task]:
        """Retorna a tarefa raiz e todos os descendentes em BFS."""
        rows = await self._pool.fetch(
            """
            WITH RECURSIVE tree AS (
                SELECT * FROM tasks WHERE id = $1
                UNION ALL
                SELECT t.* FROM tasks t
                JOIN tree tr ON t.parent_id = tr.id
            )
            SELECT * FROM tree ORDER BY created_at
            """,
            task_id,
        )
        return [_row_to_task(r) for r in rows]

    async def cancel(self, task_id: UUID) -> bool:
        result = await self._pool.execute(
            """
            UPDATE tasks SET status = 'failed', error = 'cancelled'
            WHERE id = $1 AND status IN ('pending', 'running')
            """,
            task_id,
        )
        return result == "UPDATE 1"

    async def record_subagent_run(
        self,
        *,
        task_id: UUID,
        parent_task: UUID,
        tools_used: list[str],
        duration_ms: int,
        success: bool,
        summary: str,
        raw_trace: dict | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO subagent_runs
                (task_id, parent_task, tools_used, duration_ms, success, summary, raw_trace)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            task_id,
            parent_task,
            tools_used,
            duration_ms,
            success,
            summary,
            json.dumps(raw_trace, ensure_ascii=False) if raw_trace else None,
        )


def _row_to_task(row: asyncpg.Record) -> Task:
    result = row["result"]
    if isinstance(result, str):
        result = json.loads(result)

    return Task(
        id=row["id"],
        parent_id=row["parent_id"],
        cron_job_id=row["cron_job_id"],
        source=TaskSource(row["source"]) if row["source"] in TaskSource._value2member_map_ else row["source"],
        content=row["content"],
        tier=row["tier"],
        status=TaskStatus(row["status"]),
        result=result,
        error=row["error"],
        iterations=row["iterations"] or 0,
        tokens_in=row["tokens_in"] or 0,
        tokens_out=row["tokens_out"] or 0,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        created_at=row["created_at"],
    )
