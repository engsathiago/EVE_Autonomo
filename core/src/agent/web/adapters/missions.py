"""Adapter fino para missões (F7)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.missions.planner import MissionPlanner
    from agent.missions.store import MissionStore

log = get_logger(__name__)


async def list_missions(
    store: MissionStore,
    status: str | None = None,
    tier: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        from agent.missions.store import MissionStatus

        status_filter: MissionStatus | None = status  # type: ignore[assignment]
        rows = await store.list_by_status(status_filter)
        missions = []
        for m in rows[offset : offset + limit]:
            d = m.model_dump()
            d["id"] = str(d["id"])
            if d.get("parent_mission_id"):
                d["parent_mission_id"] = str(d["parent_mission_id"])
            missions.append(d)
        return missions
    except Exception as exc:
        log.error("web.adapter.missions.list_error", error=str(exc))
        return []


async def get_mission(store: MissionStore, mission_id: str) -> dict[str, Any] | None:
    try:
        uid = UUID(mission_id)
        m = await store.get(uid)
        if m is None:
            return None
        d = m.model_dump()
        d["id"] = str(d["id"])
        if d.get("parent_mission_id"):
            d["parent_mission_id"] = str(d["parent_mission_id"])
        return d
    except Exception as exc:
        log.error("web.adapter.missions.get_error", error=str(exc), mission_id=mission_id)
        return None


async def create_mission(
    store: MissionStore,
    planner: MissionPlanner,
    title: str,
    prompt: str,
    tier: str | None = None,
) -> dict[str, Any] | None:
    try:
        import uuid as _uuid
        from datetime import UTC, datetime

        from agent.missions.store import Mission

        mission = Mission(
            id=_uuid.uuid4(),
            title=title,
            objective=prompt,
            success_criteria=[{"description": "conclusão da missão"}],
            deadline=None,
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            source="web",
            source_ref=None,
            parent_mission_id=None,
            metadata={"tier": tier} if tier else {},
        )
        created = await store.create(mission)
        d = created.model_dump()
        d["id"] = str(d["id"])
        return d
    except Exception as exc:
        log.error("web.adapter.missions.create_error", error=str(exc))
        return None


async def pause_mission(store: MissionStore, mission_id: str) -> bool:
    try:
        await store.update_status(UUID(mission_id), "paused")
        return True
    except Exception as exc:
        log.error("web.adapter.missions.pause_error", error=str(exc))
        return False


async def resume_mission(store: MissionStore, mission_id: str) -> bool:
    try:
        await store.update_status(UUID(mission_id), "active")
        return True
    except Exception as exc:
        log.error("web.adapter.missions.resume_error", error=str(exc))
        return False
