"""
SkillDecayManager (Fase 9): declara e arquiva skills inúteis.

Roda via APScheduler (job da F6), diariamente às 3h.
Regras:
  - Ativa sem uso em ≥30 dias → deprecated → move para _archive/
  - >40% erro nas últimas 10 execuções → flagged_for_review
  - version=1, aprovada ≥7 dias, ≥20 execuções bem-sucedidas → mature
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.skills.registry import SkillRegistry

log = get_logger(__name__)

_INACTIVE_DAYS = 30
_ERROR_RATE_THRESHOLD = 0.40
_MIN_EXECUTIONS_FOR_ERROR_RATE = 10
_MATURE_MIN_DAYS = 7
_MATURE_MIN_SUCCESSES = 20


class SkillDecayManager:
    def __init__(
        self,
        registry: SkillRegistry,
        active_dir: Path,
        archive_dir: Path,
    ) -> None:
        self._registry = registry
        self._active_dir = active_dir
        self._archive_dir = archive_dir

    async def scan(self, *, now: datetime | None = None) -> dict[str, int]:
        """
        Varre skills ativas e aplica regras de decay.
        Retorna dict com contagens: deprecated, flagged, matured.
        """
        now = now or datetime.now(tz=UTC)
        skills = await self._registry.list(status="active")
        counts = {"deprecated": 0, "flagged": 0, "matured": 0}

        for skill in skills:
            slug = skill["slug"]
            try:
                action = await self._evaluate(skill, now)
                if action == "deprecated":
                    await self._deprecate(slug, skill)
                    counts["deprecated"] += 1
                elif action == "flagged_for_review":
                    await self._flag(slug)
                    counts["flagged"] += 1
                elif action == "mature":
                    await self._mature(slug)
                    counts["matured"] += 1
            except Exception as exc:
                log.warning("decay.evaluate_failed", slug=slug, error=str(exc))

        log.info("decay.scan_done", **counts)
        return counts

    async def _evaluate(self, skill: dict[str, Any], now: datetime) -> str | None:
        slug = skill["slug"]

        # Regra 1: sem uso em 30 dias → deprecated
        last_used = skill.get("last_used_at")
        promoted_at = skill.get("promoted_at")
        if last_used is None and promoted_at is not None:
            if _days_since(promoted_at, now) >= _INACTIVE_DAYS:
                return "deprecated"
        elif last_used is not None:
            if _days_since(last_used, now) >= _INACTIVE_DAYS:
                return "deprecated"

        # Regra 2: >40% erro nas últimas 10 execuções → flagged_for_review
        recent = await self._registry.recent_executions(slug, limit=10)
        if len(recent) >= _MIN_EXECUTIONS_FOR_ERROR_RATE:
            failures = sum(1 for r in recent if not r["success"])
            error_rate = failures / len(recent)
            if error_rate > _ERROR_RATE_THRESHOLD:
                return "flagged_for_review"

        # Regra 3: mature
        if (
            skill.get("version") == 1
            and promoted_at is not None
            and _days_since(promoted_at, now) >= _MATURE_MIN_DAYS
            and (skill.get("successes_count") or 0) >= _MATURE_MIN_SUCCESSES
        ):
            return "mature"

        return None

    async def _deprecate(self, slug: str, skill: dict[str, Any]) -> None:
        await self._registry.update_status(slug, "deprecated")
        src = self._active_dir / slug
        dst = self._archive_dir / slug
        if src.exists():
            self._archive_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            shutil.rmtree(src)
        await _emit("skill.deprecated", {"slug": slug, "reason": "inactive_30_days"})
        log.info("decay.deprecated", slug=slug)

    async def _flag(self, slug: str) -> None:
        await self._registry.update_status(slug, "flagged_for_review")
        await _emit("skill.flagged", {"slug": slug, "reason": "error_rate_exceeded"})
        log.info("decay.flagged", slug=slug)

    async def _mature(self, slug: str) -> None:
        await self._registry.update_status(slug, "mature")
        await _emit("skill.matured", {"slug": slug, "reason": "stable_usage"})
        log.info("decay.matured", slug=slug)


def _days_since(dt: Any, now: datetime) -> float:
    if isinstance(dt, str):
        from datetime import datetime as _dt

        dt = _dt.fromisoformat(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (now - dt).total_seconds() / 86400


async def _emit(event_type: str, data: dict[str, Any]) -> None:
    try:
        from agent.events import emit_skill_event

        await emit_skill_event(event_type, data)
    except Exception:
        pass
