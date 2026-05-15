"""Adapter fino para skills (F3 + F9)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.skills.manager import SkillManager

log = get_logger(__name__)


async def list_skills(manager: "SkillManager", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    try:
        all_skills = manager.list()
        result = []
        for s in all_skills[offset:offset + limit]:
            result.append({
                "name": s.name,
                "description": s.description,
                "tags": s.tags,
                "version": s.version,
                "origin": getattr(s, "origin", "manual"),
                "uses": getattr(s, "uses", 0),
                "score": getattr(s, "critic_score", None),
                "irreversible": getattr(s, "irreversible", False),
                "status": getattr(s, "status", "active"),
            })
        return result
    except Exception as exc:
        log.error("web.adapter.skills.list_error", error=str(exc))
        return []


async def get_skill(manager: "SkillManager", name: str) -> dict[str, Any] | None:
    try:
        if not manager.has(name):
            return None
        s = manager.get(name)
        return {
            "name": s.name,
            "description": s.description,
            "tags": s.tags,
            "version": s.version,
            "origin": getattr(s, "origin", "manual"),
            "uses": getattr(s, "uses", 0),
            "score": getattr(s, "critic_score", None),
            "irreversible": getattr(s, "irreversible", False),
            "status": getattr(s, "status", "active"),
            "steps": getattr(s, "steps", []),
        }
    except Exception as exc:
        log.error("web.adapter.skills.get_error", error=str(exc), name=name)
        return None


async def disable_skill(manager: "SkillManager", name: str) -> bool:
    try:
        if not manager.has(name):
            return False
        s = manager.get(name)
        # Marca como inactive no objeto em memória; persistência depende do SkillRegistry F9
        if hasattr(s, "status"):
            object.__setattr__(s, "status", "inactive")
        return True
    except Exception as exc:
        log.error("web.adapter.skills.disable_error", error=str(exc), name=name)
        return False
