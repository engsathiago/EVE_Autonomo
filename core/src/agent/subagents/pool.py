"""
SubagentPool: cria, executa e destrói subagentes.

Aprovações: quando o filho retorna AgentResult.approval_request preenchido,
o pool cria o approval via ApprovalManager (com channel_ref do pai) e aguarda
decisão via asyncio.Event registrado no manager.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from agent.core import AgentResult
from agent.observability.logger import get_logger
from agent.subagents.context import SubAgentContext
from agent.subagents.subagent import build_subagent
from agent.tasks.task import Task, TaskSource, TaskStatus

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager
    from agent.models.router import ModelRouter
    from agent.tasks.store import TaskStore

log = get_logger(__name__)


class SubagentPool:
    def __init__(
        self,
        model_router: ModelRouter,
        task_store: TaskStore,
        approval_manager: ApprovalManager | None = None,
        max_concurrent: int = 8,
        hard_timeout_s: int = 300,
    ) -> None:
        self._model_router = model_router
        self._task_store = task_store
        self._approval_manager = approval_manager
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._hard_timeout_s = hard_timeout_s

    async def spawn(
        self,
        context: SubAgentContext,
        parent_task: Task,
    ) -> AgentResult:
        """Cria um subagente, executa com timeout e retorna o resultado."""
        async with self._semaphore:
            return await self._run_one(context, parent_task)

    async def spawn_parallel(
        self,
        contexts: list[SubAgentContext],
        parent_task: Task,
    ) -> list[AgentResult]:
        """Executa N subagentes em paralelo; retorna resultados na mesma ordem."""
        coros = [self.spawn(ctx, parent_task) for ctx in contexts]
        return list(await asyncio.gather(*coros, return_exceptions=False))

    async def _run_one(
        self,
        context: SubAgentContext,
        parent_task: Task,
    ) -> AgentResult:
        child_task = Task(
            content=context.task,
            source=TaskSource.SUBAGENT,
            parent_id=parent_task.id,
            channel_target=parent_task.channel_target,
            channel_ref=parent_task.channel_ref,
        )
        await self._task_store.create(child_task)
        await self._task_store.update_status(child_task.id, TaskStatus.RUNNING)

        agent = build_subagent(context, self._model_router)
        start_ms = int(time.monotonic() * 1000)

        log.info(
            "subagent.spawned",
            parent_id=str(parent_task.id),
            child_id=str(child_task.id),
            tools=context.tools_allowed,
        )

        try:
            result = await asyncio.wait_for(
                agent.run(
                    goal=context.build_user_message(),
                    conversation_history=[],
                ),
                timeout=self._hard_timeout_s,
            )
        except TimeoutError:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            await self._task_store.update_status(
                child_task.id,
                TaskStatus.TIMEOUT,
                error="hard_timeout",
                iterations=0,
            )
            await self._task_store.record_subagent_run(
                task_id=child_task.id,
                parent_task=parent_task.id,
                tools_used=context.tools_allowed,
                duration_ms=duration_ms,
                success=False,
                summary="timeout",
            )
            log.info("subagent.timeout", child_id=str(child_task.id))
            # Retorna resultado de timeout mas não lança exceção — pai decide retry
            return AgentResult(
                final_text="",
                iterations=0,
                total_input_tokens=0,
                total_output_tokens=0,
                estimated_cost_usd=0.0,
                duration_s=self._hard_timeout_s,
                conversation_id=str(child_task.id),
                approval_request={"error": "timeout"},
            )

        duration_ms = int(time.monotonic() * 1000) - start_ms

        # Approval propagation: filho encontrou tool sensível
        if result.approval_request and self._approval_manager:
            result = await self._handle_approval(result, child_task, parent_task, context)

        status = TaskStatus.DONE if not result.approval_request else TaskStatus.FAILED
        await self._task_store.update_status(
            child_task.id,
            status,
            iterations=result.iterations,
            tokens_in=result.total_input_tokens,
            tokens_out=result.total_output_tokens,
        )
        await self._task_store.record_subagent_run(
            task_id=child_task.id,
            parent_task=parent_task.id,
            tools_used=context.tools_allowed,
            duration_ms=duration_ms,
            success=(status == TaskStatus.DONE),
            summary=result.final_text[:500] if result.final_text else "",
            raw_trace={"iterations": result.iterations, "cost_usd": result.estimated_cost_usd},
        )

        log.info(
            "subagent.finished",
            child_id=str(child_task.id),
            success=(status == TaskStatus.DONE),
            iterations=result.iterations,
            tokens=result.total_input_tokens + result.total_output_tokens,
        )
        return result

    async def _handle_approval(
        self,
        result: AgentResult,
        child_task: Task,
        parent_task: Task,
        context: SubAgentContext,
    ) -> AgentResult:
        """
        Propaga approval do subagente para o canal do pai.

        Fluxo:
        1. Cria approval via ApprovalManager (com channel_ref do pai)
        2. Registra asyncio.Event no manager keyed pelo approval_id
        3. Aguarda evento (timeout=hard_timeout_s)
        4. Se aprovado: devolve resultado original; se negado: marca erro
        """
        assert self._approval_manager is not None
        req = result.approval_request or {}

        try:
            approval = await self._approval_manager.create(
                session_id=str(child_task.id),
                skill_name=req.get("skill_name", "subagent_action"),
                skill_args=req.get("skill_args", {}),
                summary=req.get("summary", "Subagente precisa de aprovação"),
                channel=parent_task.channel_ref.get("source", "telegram"),
                channel_ref=parent_task.channel_ref,
                expires_in_s=self._hard_timeout_s,
            )

            event = asyncio.Event()
            self._approval_manager.register_event(approval.approval_id, event)

            try:
                await asyncio.wait_for(event.wait(), timeout=self._hard_timeout_s)
            except TimeoutError:
                return AgentResult(
                    final_text="",
                    iterations=result.iterations,
                    total_input_tokens=result.total_input_tokens,
                    total_output_tokens=result.total_output_tokens,
                    estimated_cost_usd=result.estimated_cost_usd,
                    duration_s=result.duration_s,
                    conversation_id=result.conversation_id,
                    approval_request={"error": "approval_timeout"},
                )

            decision = await self._approval_manager.get(approval.approval_id)
            if decision and decision.status == "approved":
                # Approval obtido: retorna resultado sem o flag de approval
                return AgentResult(
                    final_text=result.final_text,
                    iterations=result.iterations,
                    total_input_tokens=result.total_input_tokens,
                    total_output_tokens=result.total_output_tokens,
                    estimated_cost_usd=result.estimated_cost_usd,
                    duration_s=result.duration_s,
                    conversation_id=result.conversation_id,
                )
            else:
                return AgentResult(
                    final_text="",
                    iterations=result.iterations,
                    total_input_tokens=result.total_input_tokens,
                    total_output_tokens=result.total_output_tokens,
                    estimated_cost_usd=result.estimated_cost_usd,
                    duration_s=result.duration_s,
                    conversation_id=result.conversation_id,
                    approval_request={"error": "approval_rejected"},
                )
        except Exception as exc:
            log.warning("subagent.approval.failed", error=str(exc))
            return result
