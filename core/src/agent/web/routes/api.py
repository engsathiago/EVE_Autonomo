"""Endpoints REST /api/v1/* para o Web UI (F11).

Todos exigem autenticação via X-Agent-Token.
Timeout duro: 2s para queries de DB, 5s para busca semântica.
Paginação: default 50, max 200.
Rate limit: 60 req/s por endpoint (aplicado no middleware do server.py).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agent.observability.logger import get_logger
from agent.web.auth import require_token

log = get_logger(__name__)

_DB_TIMEOUT_S = 2.0
_SEARCH_TIMEOUT_S = 5.0
_PAGE_DEFAULT = 50
_PAGE_MAX = 200

# Referências lazy para os subsistemas — preenchidas pelo server.py
_missions_store = None
_missions_planner = None
_missions_reflector = None
_skill_manager = None
_memory_store = None
_task_store = None
_db_pool = None
_critic_pool = None
_subagent_pool = None
_approval_manager = None
_orchestrator = None


def configure(
    missions_store=None,
    missions_planner=None,
    missions_reflector=None,
    skill_manager=None,
    memory_store=None,
    task_store=None,
    db_pool=None,
    subagent_pool=None,
    approval_manager=None,
    orchestrator=None,
) -> None:
    global _missions_store, _missions_planner, _missions_reflector
    global _skill_manager, _memory_store, _task_store, _db_pool
    global _subagent_pool, _approval_manager, _orchestrator
    _missions_store = missions_store
    _missions_planner = missions_planner
    _missions_reflector = missions_reflector
    _skill_manager = skill_manager
    _memory_store = memory_store
    _task_store = task_store
    _db_pool = db_pool
    _subagent_pool = subagent_pool
    _approval_manager = approval_manager
    _orchestrator = orchestrator


def _paged(limit: int, offset: int) -> tuple[int, int]:
    return min(limit, _PAGE_MAX), max(0, offset)


async def _with_db_timeout(coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=_DB_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timeout de banco de dados")


async def _with_search_timeout(coro: Any) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=_SEARCH_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timeout de busca semântica")


# ── Schemas ───────────────────────────────────────────────────────────────────

class MissionCreate(BaseModel):
    title: str
    prompt: str
    tier: str | None = None


class ApprovalDecision(BaseModel):
    decision: str  # "approve" | "reject"
    note: str | None = None


class MemorySearch(BaseModel):
    query: str
    k: int = 10
    filter: str | None = None


# ── Router ────────────────────────────────────────────────────────────────────

def make_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    # ── Missões ───────────────────────────────────────────────────────────────

    @router.get("/missions")
    async def list_missions(
        status: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.missions import list_missions as _list
        if _missions_store is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(_list(_missions_store, status, tier, since, lim, off))
        return {"items": items, "total": len(items), "limit": lim, "offset": off}

    @router.post("/missions")
    async def create_mission(body: MissionCreate) -> dict[str, Any]:
        from agent.web.adapters.missions import create_mission as _create
        if _missions_store is None or _missions_planner is None:
            raise HTTPException(status_code=503, detail="Missões indisponíveis")
        result = await _with_db_timeout(_create(_missions_store, _missions_planner, body.title, body.prompt, body.tier))
        if result is None:
            raise HTTPException(status_code=500, detail="Erro ao criar missão")
        return result

    @router.get("/missions/{mission_id}")
    async def get_mission(mission_id: str) -> dict[str, Any]:
        from agent.web.adapters.missions import get_mission as _get
        if _missions_store is None:
            raise HTTPException(status_code=503, detail="Missões indisponíveis")
        result = await _with_db_timeout(_get(_missions_store, mission_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Missão não encontrada")
        return result

    @router.post("/missions/{mission_id}/pause")
    async def pause_mission(mission_id: str) -> dict[str, Any]:
        from agent.web.adapters.missions import pause_mission as _pause
        if _missions_store is None:
            raise HTTPException(status_code=503, detail="Missões indisponíveis")
        ok = await _with_db_timeout(_pause(_missions_store, mission_id))
        return {"ok": ok}

    @router.post("/missions/{mission_id}/resume")
    async def resume_mission(mission_id: str) -> dict[str, Any]:
        from agent.web.adapters.missions import resume_mission as _resume
        if _missions_store is None:
            raise HTTPException(status_code=503, detail="Missões indisponíveis")
        ok = await _with_db_timeout(_resume(_missions_store, mission_id))
        return {"ok": ok}

    # ── Skills ────────────────────────────────────────────────────────────────

    @router.get("/skills")
    async def list_skills(
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.skills import list_skills as _list
        if _skill_manager is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(_list(_skill_manager, lim, off))
        return {"items": items, "total": len(items)}

    @router.get("/skills/{name}")
    async def get_skill(name: str) -> dict[str, Any]:
        from agent.web.adapters.skills import get_skill as _get
        if _skill_manager is None:
            raise HTTPException(status_code=503, detail="Skills indisponíveis")
        result = await _with_db_timeout(_get(_skill_manager, name))
        if result is None:
            raise HTTPException(status_code=404, detail="Skill não encontrada")
        return result

    @router.post("/skills/{name}/disable")
    async def disable_skill(name: str) -> dict[str, Any]:
        from agent.web.adapters.skills import disable_skill as _disable
        if _skill_manager is None:
            raise HTTPException(status_code=503, detail="Skills indisponíveis")
        ok = await _with_db_timeout(_disable(_skill_manager, name))
        return {"ok": ok}

    # ── Memória ───────────────────────────────────────────────────────────────

    @router.post("/memory/search")
    async def search_memory(body: MemorySearch) -> dict[str, Any]:
        from agent.web.adapters.memory import search_memory as _search
        if _memory_store is None:
            return {"items": [], "total": 0}
        items = await _with_search_timeout(_search(_memory_store, body.query, body.k, body.filter))
        return {"items": items, "total": len(items)}

    # ── Traces ────────────────────────────────────────────────────────────────

    @router.get("/traces")
    async def list_traces(
        mission_id: str | None = None,
        tier: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.traces import list_traces as _list
        if _task_store is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(_list(_task_store, mission_id, tier, status, lim, off))
        return {"items": items, "total": len(items)}

    @router.get("/traces/{trace_id}")
    async def get_trace(trace_id: str) -> dict[str, Any]:
        from agent.web.adapters.traces import get_trace as _get
        if _task_store is None:
            raise HTTPException(status_code=503, detail="Traces indisponíveis")
        result = await _with_db_timeout(_get(_task_store, trace_id))
        if result is None:
            raise HTTPException(status_code=404, detail="Trace não encontrado")
        return result

    # ── Crítico ───────────────────────────────────────────────────────────────

    @router.get("/critic/queue")
    async def critic_queue(
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.critic import get_critic_queue
        if _db_pool is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(get_critic_queue(_db_pool, lim, off))
        return {"items": items, "total": len(items)}

    @router.get("/critic/history")
    async def critic_history(
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.critic import get_critic_history
        if _db_pool is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(get_critic_history(_db_pool, lim, off))
        return {"items": items, "total": len(items)}

    # ── Subagentes ────────────────────────────────────────────────────────────

    @router.get("/subagents")
    async def subagents_health() -> dict[str, Any]:
        from agent.web.adapters.subagents import get_subagents_health
        return await _with_db_timeout(get_subagents_health(_subagent_pool, _db_pool))

    # ── Aprovações ────────────────────────────────────────────────────────────

    @router.get("/approvals")
    async def list_approvals(
        limit: int = Query(default=_PAGE_DEFAULT, le=_PAGE_MAX),
        offset: int = 0,
    ) -> dict[str, Any]:
        from agent.web.adapters.approvals import list_pending
        if _approval_manager is None:
            return {"items": [], "total": 0}
        lim, off = _paged(limit, offset)
        items = await _with_db_timeout(list_pending(_approval_manager, lim, off))
        return {"items": items, "total": len(items)}

    @router.post("/approvals/{approval_id}")
    async def decide_approval(approval_id: str, body: ApprovalDecision) -> dict[str, Any]:
        from agent.web.adapters.approvals import decide_approval as _decide
        if _approval_manager is None:
            raise HTTPException(status_code=503, detail="Aprovações indisponíveis")
        if body.decision not in ("approve", "reject"):
            raise HTTPException(status_code=400, detail="decision deve ser 'approve' ou 'reject'")
        ok = await _with_db_timeout(_decide(_approval_manager, approval_id, body.decision, body.note))
        return {"ok": ok}

    # ── Métricas de evolução ──────────────────────────────────────────────────

    @router.get("/metrics/summary")
    async def metrics_summary() -> dict[str, Any]:
        import time as _time
        summary: dict[str, Any] = {
            "skills_created_7d": 0,
            "skills_created_30d": 0,
            "missions_completed": 0,
            "critic_approval_rate": None,
            "uptime_s": None,
            "avg_duration_by_tier": {},
        }
        try:
            if _db_pool:
                rows = await _with_db_timeout(_db_pool.fetch(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE created_at > now() - interval '7 days') AS skills_7d,
                        COUNT(*) FILTER (WHERE created_at > now() - interval '30 days') AS skills_30d
                    FROM skill_invocations
                    """
                ))
                if rows:
                    summary["skills_created_7d"] = int(rows[0]["skills_7d"] or 0)
                    summary["skills_created_30d"] = int(rows[0]["skills_30d"] or 0)

                rows2 = await _with_db_timeout(_db_pool.fetch(
                    "SELECT COUNT(*) AS n FROM missions WHERE status = 'done'"
                ))
                if rows2:
                    summary["missions_completed"] = int(rows2[0]["n"] or 0)

                rows3 = await _with_db_timeout(_db_pool.fetch(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE final_verdict->>'approve' = 'true') AS approved,
                        COUNT(*) AS total
                    FROM critic_evaluations WHERE final_verdict IS NOT NULL
                    """
                ))
                if rows3 and rows3[0]["total"]:
                    summary["critic_approval_rate"] = round(
                        float(rows3[0]["approved"]) / float(rows3[0]["total"]), 3
                    )
        except Exception as exc:
            log.warning("web.metrics_summary.error", error=str(exc))

        # Uptime do processo
        try:
            from agent.deploy.metrics import _START_TIME
            summary["uptime_s"] = int(_time.time() - _START_TIME)
        except Exception:
            pass

        return summary

    # ── Informações do sistema ────────────────────────────────────────────────

    @router.get("/system/info")
    async def system_info() -> dict[str, Any]:
        import subprocess
        from agent import __version__
        info: dict[str, Any] = {"version": __version__, "phase": "F11"}
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL, text=True,
            ).strip()
            info["branch"] = branch
        except Exception:
            info["branch"] = None
        try:
            tag = subprocess.check_output(
                ["git", "describe", "--tags", "--exact-match"],
                stderr=subprocess.DEVNULL, text=True,
            ).strip()
            info["tag"] = tag
        except Exception:
            info["tag"] = None
        return info

    return router
