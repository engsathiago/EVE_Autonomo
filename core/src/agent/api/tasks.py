from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.tasks.task import TaskStatus


class TaskResponse(BaseModel):
    id: str
    parent_id: str | None
    source: str
    content: str
    tier: str | None
    status: str
    iterations: int
    tokens_in: int
    tokens_out: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def make_tasks_router(
    get_task_store: Any,
    get_orchestrator: Any,
) -> APIRouter:
    router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

    @router.get("", response_model=list[TaskResponse])
    async def list_tasks(status: str | None = None, limit: int = 50) -> Any:
        store = get_task_store()
        task_status = TaskStatus(status) if status else None
        tasks = await store.list_by_status(task_status, limit=limit)
        return [_task_response(t) for t in tasks]

    @router.get("/{task_id}", response_model=TaskResponse)
    async def get_task(task_id: UUID) -> Any:
        store = get_task_store()
        task = await store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task não encontrada")
        return _task_response(task)

    @router.get("/{task_id}/tree", response_model=list[TaskResponse])
    async def get_tree(task_id: UUID) -> Any:
        store = get_task_store()
        tasks = await store.get_tree(task_id)
        if not tasks:
            raise HTTPException(status_code=404, detail="task não encontrada")
        return [_task_response(t) for t in tasks]

    @router.post("/{task_id}/cancel")
    async def cancel_task(task_id: UUID) -> dict[str, Any]:
        store = get_task_store()
        ok = await store.cancel(task_id)
        if not ok:
            raise HTTPException(status_code=404, detail="task não encontrada ou já finalizada")
        return {"ok": True}

    @router.get("/orchestrator/stats")
    async def orchestrator_stats() -> dict[str, Any]:
        orchestrator = get_orchestrator()
        if orchestrator is None:
            return {"error": "orchestrator não inicializado"}
        return orchestrator.stats()

    return router


def _task_response(task: Any) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        parent_id=str(task.parent_id) if task.parent_id else None,
        source=str(task.source),
        content=task.content[:200],
        tier=task.tier,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        iterations=task.iterations,
        tokens_in=task.tokens_in,
        tokens_out=task.tokens_out,
        error=task.error,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )
