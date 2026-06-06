"""
MissionExecutor: executa um step de missão com D.1 (tool routing) e D.4 (Critic).

Separa a lógica de execução do AutonomousLoop para um módulo testável.
O loop delega para cá; este módulo não chama LLM diretamente.

Invariantes:
- resolve_tools_for_step é chamado antes de qualquer spawn (D.1).
- log_routing_audit é chamado por step (garante step_tool_routing != 0).
- critic_blocked vem do AgentResult — Critic wired no AIAgent._execute_tools (D.4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.execution.validation import ExecutionAnalysis, ExecutionVerdict, analyze_turn
from agent.missions.store import MissionStep
from agent.observability.logger import get_logger
from agent.orchestrator.tiers import ExecutionTier
from agent.orchestrator.tool_router import (
    StepSpec,
    log_routing_audit,
    resolve_tools_for_step,
    validate_declared_tools,
)
from agent.subagents.pool import MissingRequiredTool
from agent.tasks.task import Task, TaskSource

if TYPE_CHECKING:
    from agent.missions.store import MissionStore
    from agent.models.router import ModelRouter
    from agent.orchestrator.router import Orchestrator
    from agent.tasks.store import TaskStore

log = get_logger(__name__)

# Tier padrão para steps de missão — STRATEGIC para ter acesso amplo de tools.
_MISSION_TIER = ExecutionTier.STRATEGIC


class MissionExecutor:
    """
    Executa steps individuais de missão com D.1 e D.4 integrados.

    D.1: resolve tools via ToolRouter antes do spawn do subagent.
         Grava step_tool_routing por step (auditoria garantida).
    D.4: detecta critic_blocked no AgentResult após execução.
         Marca step como blocked_by_critic sem travar a missão.
    """

    def __init__(
        self,
        mission_store: "MissionStore",
        orchestrator: "Orchestrator",
        task_store: "TaskStore",
        model_router: "ModelRouter | None" = None,
        db_pool: Any | None = None,
    ) -> None:
        self._mission_store = mission_store
        self._orchestrator = orchestrator
        self._task_store = task_store
        self._model_router = model_router
        self._db_pool = db_pool

    async def execute_step(
        self,
        mission: Any,
        step: MissionStep,
    ) -> tuple[bool, str]:
        """
        Executa um step com D.1 routing + D.4 Critic check.

        Returns:
            (success: bool, result_code: str)
            result_code: done | failed_missing_tool | blocked_by_critic |
                         failed | prose_only | exception
        """
        # ── D.1: resolve tools antes de spawn ────────────────────────────────
        step_spec = StepSpec(
            description=step.description,
            tools_required=list(step.tools_required),
        )

        resolution = await resolve_tools_for_step(
            step_spec,
            _MISSION_TIER,
            model_router=self._model_router,
        )

        # Detecta tools declaradas ausentes do registry ANTES de tentar spawn.
        # Só aplica quando source=declared (tools explicitamente listadas).
        if resolution.source == "declared":
            missing = validate_declared_tools(list(step.tools_required))
            if missing:
                log.warning(
                    "mission_executor.step.missing_declared_tools",
                    step_id=str(step.id),
                    missing=missing,
                )
                if self._db_pool is not None:
                    await log_routing_audit(
                        step.id, _MISSION_TIER.value, resolution, self._db_pool
                    )
                await self._mission_store.update_step(
                    step.id,
                    status="failed_missing_tool",
                    error=f"missing_tools: {missing}",
                )
                return False, "failed_missing_tool"

        # Grava auditoria de routing (D.1) — garante >=1 linha em step_tool_routing por step.
        if self._db_pool is not None:
            await log_routing_audit(
                step.id, _MISSION_TIER.value, resolution, self._db_pool
            )

        log.info(
            "mission_executor.step.tools_resolved",
            step_id=str(step.id),
            source=resolution.source,
            tools=resolution.tools,
        )

        # ── Cria task e despacha para o Orchestrator ─────────────────────────
        task = Task(
            content=step.description,
            source=TaskSource.CRON,
            channel_ref={
                "mission_id": str(mission.id),
                "step_id": str(step.id),
            },
            tools_required=resolution.tools,
        )

        try:
            await self._task_store.create(task)
            await self._mission_store.update_step(
                step.id, status="running", task_id=task.id
            )
            result = await self._orchestrator.route(task)

        except MissingRequiredTool as exc:
            log.warning(
                "mission_executor.step.pool_missing_tool",
                step_id=str(step.id),
                missing=exc.missing,
            )
            await self._mission_store.update_step(
                step.id,
                status="failed_missing_tool",
                error=f"missing_tools: {exc.missing}",
            )
            return False, "failed_missing_tool"

        except Exception as exc:
            log.warning(
                "mission_executor.step.route_failed",
                step_id=str(step.id),
                error=str(exc),
            )
            await self._mission_store.update_step(
                step.id,
                status="failed",
                error=str(exc),
                increment_retry=True,
            )
            return False, "failed"

        # ── D.4: Critic bloqueou alguma tool irreversível? ────────────────────
        if getattr(result, "critic_blocked", False):
            reason = getattr(result, "critic_blocked_reason", "") or ""
            log.info(
                "mission_executor.step.blocked_by_critic",
                step_id=str(step.id),
                tool=getattr(result, "critic_blocked_tool", "unknown"),
                reason=reason[:200],
            )
            await self._mission_store.update_step(
                step.id,
                status="blocked_by_critic",
                error=f"blocked_by_critic: {reason}"[:500],
            )
            return False, "blocked_by_critic"

        # ── Analisa resultado: executou tool ou só gerou prosa? ───────────────
        analysis: ExecutionAnalysis = analyze_turn(result, allow_planning=False)

        if analysis.verdict == ExecutionVerdict.EXECUTED:
            await self._mission_store.update_step(
                step.id,
                status="done",
                result={
                    "verdict": analysis.verdict.value,
                    "tools_invoked": analysis.tools_invoked,
                    "tool_call_count": analysis.tool_call_count,
                    "has_structured_output": analysis.has_structured_output,
                    "text": (result.final_text or "")[:500],
                },
            )
            log.info(
                "mission_executor.step.done",
                step_id=str(step.id),
                tools=analysis.tools_invoked,
            )
            return True, "done"

        if analysis.verdict == ExecutionVerdict.PROSE_ONLY:
            await self._mission_store.update_step(
                step.id,
                status="failed_no_execution",
                result={
                    "verdict": "prose_only",
                    "raw_text": (result.final_text or "")[:500],
                    "reason": analysis.reason,
                },
                increment_retry=True,
            )
            log.warning(
                "mission_executor.step.prose_only",
                step_id=str(step.id),
                reason=analysis.reason,
            )
            return False, "prose_only"

        # EXCEPTION ou caso inesperado
        await self._mission_store.update_step(
            step.id,
            status="failed",
            result={"verdict": analysis.verdict.value, "reason": analysis.reason},
            error=getattr(result, "exception", None) or "unknown",
            increment_retry=True,
        )
        return False, "exception"
