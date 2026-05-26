"""
AutonomousLoop: dispara steps pendentes de missões ativas para o Orchestrator.

Anti-padrão proibido: o loop NÃO chama LLM diretamente.
Só lê DB, decide o que disparar, e delega pro Orchestrator (que chama LLM).
Isso previne loop infinito de raciocínio em cima de raciocínio.

Registra-se como cron job no scheduler existente (F6):
  - Intervalo: TICK_INTERVAL_MINUTES (default 5)
  - misfire_grace_time: 120s
  - replace_existing: True (idempotente)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agent.critic.critic import CriticRejected, Decision, needs_critic
from agent.missions.store import MissionStep
from agent.observability.logger import get_logger
from agent.orchestrator.tiers import ExecutionTier
from agent.tasks.task import Task, TaskSource

if TYPE_CHECKING:
    from agent.critic.critic import Critic
    from agent.missions.reflector import MissionReflector
    from agent.missions.store import MissionStore
    from agent.orchestrator.router import Orchestrator
    from agent.tasks.store import TaskStore

log = get_logger(__name__)

MAX_STEPS_PER_TICK = 3
MAX_CONCURRENT_MISSIONS = 5
TICK_INTERVAL_MINUTES = 5
MISSION_TIMEOUT_DAYS = 60
STEP_FAILURE_RETRY_LIMIT = 3

_LOOP_JOB_ID = "autonomous_loop_tick"
_LOOP_REGISTRY: dict[int, AutonomousLoop] = {}


async def _dispatch_loop_tick(loop_id: int) -> None:
    """Callable de módulo serializável pelo APScheduler."""
    loop = _LOOP_REGISTRY.get(loop_id)
    if loop is None:
        return
    await loop.tick()


@dataclass
class LoopReport:
    tick_at: datetime
    missions_checked: int
    steps_dispatched: int
    steps_failed: int
    replans_triggered: int
    missions_completed: int
    errors: list[str] = field(default_factory=list)


class AutonomousLoop:
    def __init__(
        self,
        mission_store: MissionStore,
        orchestrator: Orchestrator,
        task_store: TaskStore,
        critic: Critic | None = None,
        reflector: MissionReflector | None = None,
        planner: Any = None,
        db_pool: Any = None,
    ) -> None:
        self._mission_store = mission_store
        self._orchestrator = orchestrator
        self._task_store = task_store
        self._critic = critic
        self._reflector = reflector
        self._planner = planner
        self._db_pool = db_pool
        self._loop_id = id(self)
        _LOOP_REGISTRY[self._loop_id] = self
        self._running = False

    async def start(self, scheduler: Any) -> None:
        """Registra tick periódico no scheduler. Idempotente."""
        from apscheduler.triggers.interval import IntervalTrigger

        try:
            scheduler.remove_job(_LOOP_JOB_ID)
        except Exception:
            pass

        scheduler.add_job(
            _dispatch_loop_tick,
            trigger=IntervalTrigger(minutes=TICK_INTERVAL_MINUTES),
            id=_LOOP_JOB_ID,
            args=[self._loop_id],
            replace_existing=True,
            misfire_grace_time=120,
            max_instances=1,
            coalesce=True,
        )
        log.info("autonomous_loop.started", interval_minutes=TICK_INTERVAL_MINUTES)

    async def stop(self, scheduler: Any) -> None:
        try:
            scheduler.remove_job(_LOOP_JOB_ID)
        except Exception:
            pass
        _LOOP_REGISTRY.pop(self._loop_id, None)
        log.info("autonomous_loop.stopped")

    async def tick(self) -> LoopReport:
        """
        Um ciclo do loop autônomo.
        Não chama LLM — só despacha pro Orchestrator.
        """
        now = datetime.now(tz=UTC)
        report = LoopReport(
            tick_at=now,
            missions_checked=0,
            steps_dispatched=0,
            steps_failed=0,
            replans_triggered=0,
            missions_completed=0,
        )

        await self._expire_stale_missions(now)

        active = await self._mission_store.list_active()
        capped = active[:MAX_CONCURRENT_MISSIONS]
        report.missions_checked = len(capped)

        steps_budget = MAX_STEPS_PER_TICK
        for mission in capped:
            if steps_budget <= 0:
                break
            dispatched, result = await self._process_mission(mission, steps_budget, report)
            steps_budget -= dispatched
            report.steps_dispatched += dispatched
            if result == "completed":
                report.missions_completed += 1

        log.info(
            "autonomous_loop.tick",
            missions=report.missions_checked,
            dispatched=report.steps_dispatched,
            completed=report.missions_completed,
        )
        return report

    async def tick_now(self) -> LoopReport:
        """Força um tick imediato (debug / CLI)."""
        return await self.tick()

    async def _process_mission(
        self, mission: Any, budget: int, report: LoopReport
    ) -> tuple[int, str]:
        pending = await self._mission_store.get_pending_steps(mission.id)
        if not pending:
            all_steps = await self._mission_store.get_all_steps(mission.id)
            if all_steps and all(s.status in ("done", "skipped") for s in all_steps):
                await self._complete_mission(mission.id)
                return 0, "completed"
            return 0, "no_steps"

        dispatched = 0
        for step in pending[:budget]:
            result = await self._dispatch_step(mission, step, report)
            if result:
                dispatched += 1

        return dispatched, "ok"

    async def _dispatch_step(self, mission: Any, step: MissionStep, report: LoopReport) -> bool:
        if step.retry_count >= STEP_FAILURE_RETRY_LIMIT:
            log.warning(
                "autonomous_loop.step.retry_limit",
                step_id=str(step.id),
                retries=step.retry_count,
            )
            await self._trigger_replan(mission, step, report)
            return False

        decision = Decision(
            tool_name="orchestrator_dispatch",
            tool_args={"step": step.description, "mission": mission.title},
            context_summary=f"Missão: {mission.title}\nStep: {step.description}",
            tier=ExecutionTier.STRATEGIC,
            mission_id=mission.id,
        )

        if self._critic is not None and needs_critic(decision):
            try:
                verdict = await self._critic.evaluate(decision, db_pool=self._db_pool)
                if verdict.verdict == "reject":
                    raise CriticRejected(verdict.reasoning)
                if verdict.verdict == "escalate":
                    log.info(
                        "autonomous_loop.critic.escalate",
                        step_id=str(step.id),
                        message=verdict.escalation_message,
                    )
                    # Propaga para gate de aprovação humana (F5 integration point)
                    # Quem chama o loop é responsável por lidar com escalate
                    await self._mission_store.update_step(
                        step.id, status="skipped", error="escalated_to_human"
                    )
                    return False
            except CriticRejected as exc:
                report.steps_failed += 1
                await self._mission_store.update_step(
                    step.id,
                    status="failed",
                    error=f"critic_rejected: {exc.reasoning}",
                    increment_retry=True,
                )
                return False

        task = Task(
            content=step.description,
            source=TaskSource.CRON,
            channel_ref={"mission_id": str(mission.id), "step_id": str(step.id)},
        )

        try:
            await self._task_store.create(task)
            await self._mission_store.update_step(step.id, status="running", task_id=task.id)
            result = await self._orchestrator.route(task)
            await self._mission_store.update_step(
                step.id,
                status="done",
                result={"text": (result.final_text or "")[:1000]},
            )
            return True
        except Exception as exc:
            log.warning(
                "autonomous_loop.step.failed",
                step_id=str(step.id),
                error=str(exc),
            )
            report.steps_failed += 1
            await self._mission_store.update_step(
                step.id,
                status="failed",
                error=str(exc),
                increment_retry=True,
            )
            return False

    async def _trigger_replan(self, mission: Any, step: MissionStep, report: LoopReport) -> None:
        if self._planner is None:
            log.warning("autonomous_loop.replan.no_planner", mission_id=str(mission.id))
            return
        try:
            new_plan = await self._planner.replan(
                mission.id,
                reason=f"Step falhou {step.retry_count}x: {step.description}",
                mission_store=self._mission_store,
            )
            all_steps = await self._mission_store.get_all_steps(mission.id)
            next_seq = max((s.sequence for s in all_steps), default=-1) + 1
            for i, desc in enumerate(new_plan.steps):
                await self._mission_store.add_step(
                    mission.id, description=desc, sequence=next_seq + i
                )
            report.replans_triggered += 1
            log.info("autonomous_loop.replan.done", mission_id=str(mission.id))
        except Exception as exc:
            log.error("autonomous_loop.replan.failed", error=str(exc))

    async def _complete_mission(self, mission_id: UUID) -> None:
        await self._mission_store.update_status(mission_id, "done")
        if self._reflector is not None:
            try:
                await self._reflector.reflect(mission_id)
            except Exception as exc:
                log.error("autonomous_loop.reflect.failed", error=str(exc))

    async def _expire_stale_missions(self, now: datetime) -> None:
        """Missões sem progresso por MISSION_TIMEOUT_DAYS → status failed."""
        cutoff = now - timedelta(days=MISSION_TIMEOUT_DAYS)
        active = await self._mission_store.list_active()
        for mission in active:
            if mission.updated_at.replace(tzinfo=UTC) < cutoff:
                log.warning(
                    "autonomous_loop.mission.timeout",
                    mission_id=str(mission.id),
                    days=MISSION_TIMEOUT_DAYS,
                )
                await self._mission_store.update_status(mission.id, "failed")
