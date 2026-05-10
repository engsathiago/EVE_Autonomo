"""Rotas REST para Missões (F7)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.observability.logger import get_logger

log = get_logger(__name__)


class PlanRequest(BaseModel):
    objective: str
    deadline: str | None = None
    source: str = "cli"


class CreateMissionRequest(BaseModel):
    objective: str
    deadline: str | None = None
    source: str = "cli"
    plan: dict[str, Any]


class UpdateStatusRequest(BaseModel):
    status: str
    reason: str | None = None


class ReplanRequest(BaseModel):
    reason: str


def make_missions_router(
    mission_store: Any,
    planner: Any,
    reflector: Any,
) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post("/plan")
    async def plan_mission(req: PlanRequest) -> dict:
        deadline_dt: datetime | None = None
        if req.deadline:
            try:
                deadline_dt = datetime.fromisoformat(req.deadline)
            except ValueError:
                raise HTTPException(400, "deadline deve ser YYYY-MM-DD")

        plan = await planner.plan(req.objective, deadline_dt)
        return {
            "title": plan.title,
            "success_criteria": plan.success_criteria,
            "steps": plan.steps,
            "is_parallel": plan.is_parallel,
        }

    @router.post("", status_code=201)
    async def create_mission(req: CreateMissionRequest) -> dict:
        deadline_dt: datetime | None = None
        if req.deadline:
            try:
                deadline_dt = datetime.fromisoformat(req.deadline)
            except ValueError:
                raise HTTPException(400, "deadline deve ser YYYY-MM-DD")

        plan = req.plan
        mission = await mission_store.create(
            title=plan.get("title", req.objective[:80]),
            objective=req.objective,
            success_criteria=plan.get("success_criteria", []),
            deadline=deadline_dt,
            source=req.source,
            source_ref=None,
        )

        steps_list = plan.get("steps", [])
        parallel_list = plan.get("is_parallel", [False] * len(steps_list))
        for i, (desc, is_par) in enumerate(zip(steps_list, parallel_list)):
            await mission_store.add_step(mission.id, description=desc, sequence=i)

        return _mission_dict(mission)

    @router.get("")
    async def list_missions(status: str | None = None) -> list[dict]:
        missions = await mission_store.list_by_status(status if status != "all" else None)
        return [_mission_dict(m) for m in missions]

    @router.get("/{mission_id}")
    async def get_mission(mission_id: UUID) -> dict:
        try:
            m = await mission_store.get(mission_id)
        except KeyError:
            raise HTTPException(404, "Missão não encontrada")
        return _mission_dict(m)

    @router.get("/{mission_id}/steps")
    async def get_steps(mission_id: UUID) -> list[dict]:
        steps = await mission_store.get_all_steps(mission_id)
        return [_step_dict(s) for s in steps]

    @router.patch("/{mission_id}/status")
    async def update_status(mission_id: UUID, req: UpdateStatusRequest) -> dict:
        valid = {"active", "paused", "done", "abandoned", "failed"}
        if req.status not in valid:
            raise HTTPException(400, f"status deve ser um de: {valid}")
        try:
            await mission_store.update_status(mission_id, req.status)
        except KeyError:
            raise HTTPException(404, "Missão não encontrada")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @router.post("/{mission_id}/replan")
    async def replan_mission(mission_id: UUID, req: ReplanRequest) -> dict:
        plan = await planner.replan(
            mission_id, reason=req.reason, mission_store=mission_store
        )
        all_steps = await mission_store.get_all_steps(mission_id)
        next_seq = max((s.sequence for s in all_steps), default=-1) + 1
        for i, desc in enumerate(plan.steps):
            await mission_store.add_step(mission_id, description=desc, sequence=next_seq + i)
        return {"steps_added": len(plan.steps)}

    @router.post("/{mission_id}/reflect")
    async def reflect_mission(mission_id: UUID) -> dict:
        reflection = await reflector.reflect(mission_id)
        return {
            "delivered": reflection.delivered,
            "quality_assessment": reflection.quality_assessment,
            "next_action": reflection.next_action,
            "learned": reflection.learned,
        }

    return router


def _mission_dict(m: Any) -> dict:
    return {
        "id": str(m.id),
        "title": m.title,
        "objective": m.objective,
        "success_criteria": m.success_criteria,
        "deadline": m.deadline.isoformat() if m.deadline else None,
        "status": m.status,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        "parent_mission_id": str(m.parent_mission_id) if m.parent_mission_id else None,
    }


def _step_dict(s: Any) -> dict:
    return {
        "id": str(s.id),
        "mission_id": str(s.mission_id),
        "sequence": s.sequence,
        "description": s.description,
        "status": s.status,
        "retry_count": s.retry_count,
        "task_id": str(s.task_id) if s.task_id else None,
    }
