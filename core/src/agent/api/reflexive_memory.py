"""Rotas REST para Memória Reflexiva (F7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from agent.observability.logger import get_logger

log = get_logger(__name__)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


def make_reflexive_memory_router(reflexive_memory: Any) -> APIRouter:
    router = APIRouter(prefix="/v1/memory/reflexive", tags=["memory"])

    @router.get("")
    async def list_insights(
        limit: int = 20,
        include_forgotten: bool = False,
    ) -> list[dict]:
        insights = await reflexive_memory.list_all(include_forgotten=include_forgotten, limit=limit)
        return [_insight_dict(i) for i in insights]

    @router.post("/search")
    async def search_insights(req: SearchRequest) -> list[dict]:
        results = await reflexive_memory.recall(req.query, top_k=req.top_k)
        return [_insight_dict(r) for r in results]

    @router.delete("/{insight_id}")
    async def forget_insight(insight_id: UUID) -> dict:
        await reflexive_memory.mark_forgotten(insight_id)
        return {"ok": True}

    return router


def _insight_dict(i: Any) -> dict:
    return {
        "id": str(i.id),
        "insight": i.insight,
        "source_mission_id": str(i.source_mission_id) if i.source_mission_id else None,
        "relevance_score": i.relevance_score,
        "times_recalled": i.times_recalled,
        "last_recalled_at": i.last_recalled_at.isoformat() if i.last_recalled_at else None,
        "created_at": i.created_at.isoformat(),
    }
