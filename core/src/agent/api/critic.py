"""Rotas REST para o Critic (F7)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from agent.critic.critic import Decision
from agent.observability.logger import get_logger

log = get_logger(__name__)


class CriticTestRequest(BaseModel):
    tool_name: str
    tool_args: dict = {}
    context_summary: str = ""


def make_critic_router(critic: Any, db_pool: Any) -> APIRouter:
    router = APIRouter(prefix="/v1/critic", tags=["critic"])

    @router.get("/evaluations")
    async def list_evaluations(
        task_id: str | None = None,
        mission_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        conditions = []
        params: list[Any] = []
        if task_id:
            conditions.append(f"task_id = ${len(params) + 1}::uuid")
            params.append(task_id)
        if mission_id:
            conditions.append(f"mission_id = ${len(params) + 1}::uuid")
            params.append(mission_id)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        query = (
            f"SELECT * FROM critic_evaluations {where}"
            f" ORDER BY created_at DESC LIMIT ${len(params)}"
        )
        rows = await db_pool.fetch(query, *params)
        return [_eval_dict(r) for r in rows]

    @router.get("/stats")
    async def critic_stats() -> dict:
        from agent.metrics.phase_7 import metrics
        snap = metrics.snapshot()
        return {
            k: v for k, v in snap.items() if "critic" in k or "step" in k
        }

    @router.post("/test")
    async def critic_test(req: CriticTestRequest) -> dict:
        decision = Decision(
            tool_name=req.tool_name,
            tool_args=req.tool_args,
            context_summary=req.context_summary,
        )
        verdict = await critic.evaluate(decision, db_pool=db_pool)
        return {
            "verdict": verdict.verdict,
            "mitigations": verdict.mitigations,
            "reasoning": verdict.reasoning,
            "escalation_message": verdict.escalation_message,
            "technical_approve": verdict.technical.approve,
            "devils_approve": verdict.devils_advocate.approve,
        }

    return router


def _eval_dict(row: Any) -> dict:
    def _parse(v: Any) -> Any:
        return json.loads(v) if isinstance(v, str) else (dict(v) if v else {})

    return {
        "id": str(row["id"]),
        "decision_id": str(row["decision_id"]),
        "task_id": str(row["task_id"]) if row["task_id"] else None,
        "mission_id": str(row["mission_id"]) if row["mission_id"] else None,
        "technical_verdict": _parse(row["technical_verdict"]),
        "devils_advocate_verdict": _parse(row["devils_advocate_verdict"]),
        "synthesizer_verdict": _parse(row["synthesizer_verdict"]),
        "final_verdict": row["final_verdict"],
        "mitigations": _parse(row["mitigations"]),
        "latency_ms": row["latency_ms"],
        "created_at": row["created_at"].isoformat(),
    }
