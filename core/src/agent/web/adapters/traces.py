"""Adapter fino para traces (tasks + subagent_runs da F6/F7)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.tasks.store import TaskStore

log = get_logger(__name__)


async def list_traces(
    store: "TaskStore",
    mission_id: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        from agent.tasks.task import TaskStatus
        status_filter = TaskStatus(status) if status else None
        tasks = await store.list_by_status(status_filter, limit=limit + offset)
        result = []
        for t in tasks[offset:offset + limit]:
            if tier and t.tier != tier:
                continue
            if mission_id:
                ref = t.channel_ref or {}
                if str(ref.get("mission_id", "")) != mission_id:
                    continue
            result.append(_task_to_dict(t))
        return result
    except Exception as exc:
        log.error("web.adapter.traces.list_error", error=str(exc))
        return []


async def get_trace(store: "TaskStore", trace_id: str) -> dict[str, Any] | None:
    try:
        uid = UUID(trace_id)
        task = await store.get(uid)
        if task is None:
            return None
        children = await store.get_tree(uid)
        d = _task_to_dict(task)
        d["steps"] = [_task_to_dict(c) for c in children if str(c.id) != trace_id]
        return d
    except Exception as exc:
        log.error("web.adapter.traces.get_error", error=str(exc))
        return None


def _task_to_dict(t: Any) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "content": t.content,
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "tier": t.tier,
        "source": t.source.value if hasattr(t.source, "value") else str(t.source),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "error": t.error,
        "parent_id": str(t.parent_id) if t.parent_id else None,
        "channel_ref": t.channel_ref,
    }
