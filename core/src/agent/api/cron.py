from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.observability.logger import get_logger
from agent.scheduler.parser import CronParseError, next_runs, parse_natural

log = get_logger(__name__)


class CronJobCreate(BaseModel):
    name: str
    schedule: str          # cron expression ou linguagem natural
    task: str              # prompt que vira Task
    source: str = "telegram"
    target: str | None = None
    metadata: dict[str, Any] = {}


class CronJobResponse(BaseModel):
    id: str
    name: str
    cron_expr: str
    nl_original: str | None
    task_tpl: str
    source: str
    target: str | None
    enabled: bool
    last_run: datetime | None
    next_run: datetime | None
    last_status: str | None
    created_at: datetime


def make_cron_router(
    get_cron_store: Any,
    get_cron_worker: Any,
    get_model_router: Any,
) -> APIRouter:
    router = APIRouter(prefix="/v1/cron", tags=["cron"])

    @router.post("/jobs", response_model=CronJobResponse, status_code=201)
    async def create_job(body: CronJobCreate) -> Any:
        cron_store = get_cron_store()
        cron_worker = get_cron_worker()
        model_router = get_model_router()

        # Detecta se é linguagem natural (contém espaço em excesso ou letras)
        schedule = body.schedule.strip()
        nl_original: str | None = None

        import re
        is_cron = bool(re.match(r"^([\d\*\/,\-]+\s+){4}[\d\*\/,\-]+\s*$", schedule))
        if not is_cron:
            nl_original = schedule
            try:
                schedule = await parse_natural(schedule, model_router)
            except CronParseError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

        nexts = next_runs(schedule, n=1)
        next_run = nexts[0] if nexts else None

        job = await cron_store.create(
            name=body.name,
            cron_expr=schedule,
            nl_original=nl_original,
            task_tpl=body.task,
            source=body.source,
            target=body.target,
            next_run=next_run,
            metadata=body.metadata,
        )
        await cron_worker.add_job(job)

        return _job_response(job, schedule)

    @router.get("/jobs", response_model=list[CronJobResponse])
    async def list_jobs(enabled_only: bool = False) -> Any:
        cron_store = get_cron_store()
        jobs = await cron_store.list(enabled_only=enabled_only)
        return [_job_response(j, j.cron_expr) for j in jobs]

    @router.get("/jobs/{job_id}", response_model=CronJobResponse)
    async def get_job(job_id: UUID) -> Any:
        cron_store = get_cron_store()
        job = await cron_store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job não encontrado")
        return _job_response(job, job.cron_expr)

    @router.patch("/jobs/{job_id}/enable")
    async def enable_job(job_id: UUID) -> dict[str, Any]:
        cron_store = get_cron_store()
        cron_worker = get_cron_worker()
        ok = await cron_store.set_enabled(job_id, True)
        if not ok:
            raise HTTPException(status_code=404, detail="job não encontrado")
        job = await cron_store.get(job_id)
        if job:
            await cron_worker.add_job(job)
        return {"ok": True}

    @router.patch("/jobs/{job_id}/disable")
    async def disable_job(job_id: UUID) -> dict[str, Any]:
        cron_store = get_cron_store()
        cron_worker = get_cron_worker()
        ok = await cron_store.set_enabled(job_id, False)
        if not ok:
            raise HTTPException(status_code=404, detail="job não encontrado")
        cron_worker.remove_job(job_id)
        return {"ok": True}

    @router.delete("/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: UUID) -> None:
        cron_store = get_cron_store()
        cron_worker = get_cron_worker()
        cron_worker.remove_job(job_id)
        ok = await cron_store.delete(job_id)
        if not ok:
            raise HTTPException(status_code=404, detail="job não encontrado")

    @router.post("/jobs/{job_id}/run-now")
    async def run_now(job_id: UUID) -> dict[str, Any]:
        """Dispara o job imediatamente fora do horário agendado (debug)."""
        cron_worker = get_cron_worker()
        cron_store = get_cron_store()
        job = await cron_store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job não encontrado")
        import asyncio
        asyncio.create_task(cron_worker._fire(job_id))
        return {"ok": True, "message": "job disparado em background"}

    return router


def _job_response(job: Any, cron_expr: str) -> CronJobResponse:
    return CronJobResponse(
        id=str(job.id),
        name=job.name,
        cron_expr=cron_expr,
        nl_original=job.nl_original,
        task_tpl=job.task_tpl,
        source=job.source,
        target=job.target,
        enabled=job.enabled,
        last_run=job.last_run,
        next_run=job.next_run,
        last_status=job.last_status,
        created_at=job.created_at,
    )
