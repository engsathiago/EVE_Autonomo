"""Rotas REST para o AutonomousLoop (F7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent.observability.logger import get_logger

log = get_logger(__name__)

_loop_paused = False


def make_loop_router(autonomous_loop: Any, mission_store: Any) -> APIRouter:
    router = APIRouter(prefix="/v1/loop", tags=["loop"])
    global _loop_paused

    @router.get("/status")
    async def loop_status() -> dict:
        missions = await mission_store.list_active()
        upcoming: list[dict] = []
        for m in missions[:5]:
            pending = await mission_store.get_pending_steps(m.id)
            for step in pending[:2]:
                upcoming.append(
                    {
                        "mission_id": str(m.id),
                        "mission_title": m.title,
                        "sequence": step.sequence,
                        "description": step.description,
                    }
                )

        from agent.autonomous.loop import TICK_INTERVAL_MINUTES

        return {
            "running": not _loop_paused,
            "missions_active": len(missions),
            "tick_interval_minutes": TICK_INTERVAL_MINUTES,
            "upcoming_steps": upcoming,
        }

    @router.post("/tick")
    async def force_tick() -> dict:
        if _loop_paused:
            raise HTTPException(409, "Loop está pausado")
        report = await autonomous_loop.tick_now()
        return {
            "tick_at": report.tick_at.isoformat(),
            "missions_checked": report.missions_checked,
            "steps_dispatched": report.steps_dispatched,
            "steps_failed": report.steps_failed,
            "replans_triggered": report.replans_triggered,
            "missions_completed": report.missions_completed,
        }

    @router.post("/pause")
    async def pause_loop() -> dict:
        global _loop_paused
        _loop_paused = True
        return {"ok": True, "running": False}

    @router.post("/resume")
    async def resume_loop() -> dict:
        global _loop_paused
        _loop_paused = False
        return {"ok": True, "running": True}

    return router
