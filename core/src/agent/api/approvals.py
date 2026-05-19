from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.approvals.manager import (
    AlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalState,
)
from agent.observability.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    decided_by: str = "user"


class DecisionResponse(BaseModel):
    status: str
    result: dict | None = None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalState]


def make_approvals_router(get_approval_manager: Any) -> APIRouter:
    @router.get("", response_model=ApprovalListResponse)
    async def list_approvals(
        status: str = "pending",
        session_id: str | None = None,
    ) -> ApprovalListResponse:
        manager = get_approval_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")
        items = await manager.list_pending(session_id=session_id)
        return ApprovalListResponse(items=items)

    @router.get("/{approval_id}", response_model=ApprovalState)
    async def get_approval(approval_id: str) -> ApprovalState:
        manager = get_approval_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")
        try:
            return await manager.get(approval_id)
        except ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="approval_not_found")

    @router.post("/{approval_id}", response_model=DecisionResponse)
    async def decide_approval(
        approval_id: str,
        req: DecisionRequest,
        skill_manager: Any = None,
    ) -> DecisionResponse:
        manager = get_approval_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")

        try:
            state = await manager.decide(approval_id, req.decision, req.decided_by)
        except ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="approval_not_found")
        except AlreadyDecidedError as exc:
            # Idempotente: retorna estado atual
            return DecisionResponse(status=exc.state.status)
        except ApprovalExpiredError:
            raise HTTPException(status_code=409, detail="approval_expired")

        if state.status == "rejected":
            log.info("approval.rejected", approval_id=approval_id, by=req.decided_by)
            return DecisionResponse(status="rejected")

        # Approved: execute the skill
        sm = get_skill_manager_fn()
        if sm is None:
            log.warning("approval.approved_but_no_skill_manager", approval_id=approval_id)
            return DecisionResponse(status="approved", result={"warning": "skill_manager unavailable"})

        try:
            manifest = sm.get(state.skill_name)
            runner = _make_runner(sm)
            skill_result = await runner.execute_approved(approval_id, manifest)
            log.info("approval.executed", approval_id=approval_id, skill=state.skill_name)
            return DecisionResponse(status="approved", result={"output": skill_result.output})
        except Exception as exc:
            log.exception("approval.execute_failed", approval_id=approval_id)
            raise HTTPException(status_code=500, detail=f"skill_execution_failed: {exc}") from exc

    # These are filled in by make_approvals_router closure
    get_skill_manager_fn: Any = lambda: None

    return router


def make_approvals_router_full(
    get_approval_manager: Any,
    get_skill_manager: Any,
) -> APIRouter:
    """Full factory with skill execution support."""
    full_router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

    @full_router.get("", response_model=ApprovalListResponse)
    async def list_approvals(
        session_id: str | None = None,
    ) -> ApprovalListResponse:
        manager = get_approval_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")
        items = await manager.list_pending(session_id=session_id)
        return ApprovalListResponse(items=items)

    @full_router.get("/{approval_id}", response_model=ApprovalState)
    async def get_approval(approval_id: str) -> ApprovalState:
        manager = get_approval_manager()
        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")
        try:
            return await manager.get(approval_id)
        except ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="approval_not_found")

    @full_router.post("/{approval_id}", response_model=DecisionResponse)
    async def decide_approval(
        approval_id: str,
        req: DecisionRequest,
    ) -> DecisionResponse:
        manager = get_approval_manager()
        sm = get_skill_manager()

        if manager is None:
            raise HTTPException(status_code=503, detail="approval_manager_not_configured")

        try:
            state = await manager.decide(approval_id, req.decision, req.decided_by)
        except ApprovalNotFoundError:
            raise HTTPException(status_code=404, detail="approval_not_found")
        except AlreadyDecidedError as exc:
            return DecisionResponse(status=exc.state.status)
        except ApprovalExpiredError:
            raise HTTPException(status_code=409, detail="approval_expired")

        if state.status == "rejected":
            log.info("approval.rejected", approval_id=approval_id, by=req.decided_by)
            return DecisionResponse(status="rejected")

        if sm is None:
            return DecisionResponse(status="approved", result={"warning": "skill_manager unavailable"})

        try:
            from agent.skills.template_runner import TemplateSkillRunner as SkillRunner
            from agent.transports import AnthropicTransport
            from agent.config import get_settings

            settings = get_settings()
            manifest = sm.get(state.skill_name)
            runner = SkillRunner(
                transport=AnthropicTransport(model=settings.anthropic.planner_model),
                model_router=sm._model_router,
                approval_manager=manager,
            )
            skill_result = await runner.execute_approved(approval_id, manifest)
            log.info("approval.executed", approval_id=approval_id, skill=state.skill_name)
            return DecisionResponse(status="approved", result={"output": skill_result.output})
        except Exception as exc:
            log.exception("approval.execute_failed", approval_id=approval_id)
            raise HTTPException(status_code=500, detail=f"skill_execution_failed: {exc}") from exc

    return full_router
