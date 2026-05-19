"""Rotas REST para Skills auto-geradas (F9)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.observability.logger import get_logger

log = get_logger(__name__)


class RunSkillRequest(BaseModel):
    input: dict[str, Any]
    mission_id: str | None = None


class RejectRequest(BaseModel):
    reason: str


class PromoteRequest(BaseModel):
    force: bool = False


def make_skills_router(
    registry: Any,        # SkillRegistry
    runner: Any,          # SkillRunner
    promoter: Any,        # SkillPromoter
    synthesizer: Any,     # SkillSynthesizer
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

    @router.get("")
    async def list_skills(status: str | None = None) -> list[dict[str, Any]]:
        return await registry.list(status=status)

    @router.get("/stats")
    async def skills_stats() -> list[dict[str, Any]]:
        return await registry.stats()

    @router.get("/{slug}")
    async def show_skill(slug: str) -> dict[str, Any]:
        try:
            return await registry.get(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.post("/{slug}/run")
    async def run_skill(slug: str, req: RunSkillRequest) -> dict[str, Any]:
        if runner is None:
            raise HTTPException(status_code=503, detail="SkillRunner não disponível")
        try:
            result = await runner.run_skill(slug, req.input, mission_id=req.mission_id)
            return {
                "slug": result.slug,
                "output": result.output,
                "execution_id": result.execution_id,
                "duration_seconds": result.duration_seconds,
            }
        except Exception as exc:
            log.exception("api.skill.run_failed", slug=slug)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/{slug}/promote")
    async def promote_skill(slug: str, req: PromoteRequest = PromoteRequest()) -> dict[str, Any]:
        if promoter is None:
            raise HTTPException(status_code=503, detail="SkillPromoter não disponível")
        try:
            from agent.skills.manifest import SkillManifestF9
            import json
            row = await registry.get(slug)
            manifest = SkillManifestF9(**json.loads(row["manifest_json"]))
            approved = await promoter.promote(manifest, force=req.force)
            return {"slug": slug, "approved": approved}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/{slug}/reject")
    async def reject_skill(slug: str, req: RejectRequest) -> dict[str, Any]:
        try:
            await registry.update_status(slug, "rejected", rejection_reason=req.reason)
            return {"slug": slug, "status": "rejected"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/{slug}/archive")
    async def archive_skill(slug: str) -> dict[str, Any]:
        try:
            await registry.update_status(slug, "deprecated")
            return {"slug": slug, "status": "deprecated"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/synthesize")
    async def synthesize_skills() -> dict[str, Any]:
        if synthesizer is None:
            raise HTTPException(status_code=503, detail="SkillSynthesizer não disponível")
        try:
            clusters = await synthesizer.scan_for_candidates()
            return {"clusters_found": len(clusters), "slugs": [c.cluster_id for c in clusters]}
        except Exception as exc:
            log.exception("api.skill.synthesize_failed")
            raise HTTPException(status_code=500, detail=str(exc))

    return router
