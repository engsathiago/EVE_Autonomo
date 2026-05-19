"""API REST para deploy (F10): backup manual e restore."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from agent.observability.logger import get_logger

log = get_logger(__name__)


class RestoreRequest(BaseModel):
    date: str
    kinds: list[str] | None = None


def make_deploy_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/deploy", tags=["deploy"])

    @router.post("/backup")
    async def trigger_backup() -> dict:
        """Dispara backup manual imediato."""
        from agent.deploy.backup import run_backup
        return await run_backup()

    @router.post("/restore")
    async def trigger_restore(req: RestoreRequest) -> dict:
        """Restaura backups de uma data específica (YYYYMMDD)."""
        from agent.deploy.restore import run_restore
        return await run_restore(date_tag=req.date, kinds=req.kinds)

    return router
