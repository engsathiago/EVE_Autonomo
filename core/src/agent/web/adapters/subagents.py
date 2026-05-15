"""Adapter fino para subagentes (F6)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.subagents.pool import SubagentPool
    import asyncpg

log = get_logger(__name__)


async def get_subagents_health(
    pool: "SubagentPool | None",
    db_pool: "asyncpg.Pool | None" = None,
) -> dict[str, Any]:
    try:
        active = 0
        capacity = 0
        if pool is not None:
            semaphore = getattr(pool, "_semaphore", None)
            if semaphore is not None:
                capacity = semaphore._value + (semaphore._bound_value - semaphore._value) if hasattr(semaphore, "_bound_value") else semaphore._value
                active = max(0, getattr(pool, "_semaphore", None) and
                             (pool._semaphore._bound_value - pool._semaphore._value
                              if hasattr(pool._semaphore, "_bound_value") else 0) or 0)

        recent_runs: list[dict] = []
        if db_pool is not None:
            try:
                rows = await db_pool.fetch(
                    """
                    SELECT sr.task_id, sr.worker_id, sr.started_at, sr.completed_at,
                           sr.error, t.tier, t.status
                    FROM subagent_runs sr
                    LEFT JOIN tasks t ON t.id = sr.task_id
                    ORDER BY sr.started_at DESC
                    LIMIT 20
                    """
                )
                recent_runs = [
                    {
                        "task_id": str(r["task_id"]),
                        "worker_id": r["worker_id"],
                        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                        "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                        "error": r["error"],
                        "tier": r["tier"],
                        "status": r["status"],
                    }
                    for r in rows
                ]
            except Exception as db_exc:
                log.warning("web.adapter.subagents.db_error", error=str(db_exc))

        return {
            "active": active,
            "capacity": capacity,
            "recent_runs": recent_runs,
        }
    except Exception as exc:
        log.error("web.adapter.subagents.health_error", error=str(exc))
        return {"active": 0, "capacity": 0, "recent_runs": [], "error": str(exc)}
