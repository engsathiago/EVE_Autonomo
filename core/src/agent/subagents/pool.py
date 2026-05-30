"""
SubagentPool: cria, executa e destrói subagentes.

Aprovações: quando o filho retorna AgentResult.approval_request preenchido,
o pool cria o approval via ApprovalManager (com channel_ref do pai) e aguarda
decisão via asyncio.Event registrado no manager.

D.1: Adiciona validação de tools DECLARADAS antes do dispatch.
Se tools_required não-vazio e alguma tool declarada estiver ausente do registry,
lança MissingRequiredTool e marca o step como 'failed_missing_tool'.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from agent.core import AgentResult
from agent.execution.validation import ExecutionVerdict, analyze_turn
from agent.observability.logger import get_logger
from agent.orchestrator.tool_router import KNOWN_BUILTIN_TOOLS, validate_declared_tools
from agent.subagents.context import SubAgentContext
from agent.subagents.subagent import build_subagent
from agent.tasks.task import Task, TaskSource, TaskStatus

if TYPE_CHECKING:
    from typing import Any

    from agent.approvals.manager import ApprovalManager
    from agent.critic.critic import Critic
    from agent.models.router import ModelRouter
    from agent.tasks.store import TaskStore

log = get_logger(__name__)


class MissingRequiredTool(Exception):
    """
    Levantado quando uma tool declarada em tools_required não existe no registry.

    Atributos:
        missing: Lista de nomes de tools ausentes.
        step_id: ID do step (string) para diagnóstico.
    """

    def __init__(self, missing: list[str], step_id: str | None = None) -> None:
        self.missing = missing
        self.step_id = step_id
        tools_str = ", ".join(missing)
        super().__init__(
            f"Tools declaradas ausentes no registry: [{tools_str}]"
            + (f" (step_id={step_id})" if step_id else "")
        )


def _validate_context_tools(context: SubAgentContext) -> list[str]:
    """
    Valida tools declaradas (ctx.tools_required) contra o registry builtin.
    Retorna lista de tools ausentes (vazia = tudo ok).

    Só executa se tools_required não-vazio (source=declared).
    Para tools inferidas, tools_required=[] e esta função retorna [].
    """
    if not context.tools_required:
        return []
    return validate_declared_tools(context.tools_required)


class SubagentPool:
    def __init__(
        self,
        model_router: ModelRouter,
        task_store: TaskStore,
        approval_manager: ApprovalManager | None = None,
        max_concurrent: int = 8,
        hard_timeout_s: int = 300,
        critic: "Critic | None" = None,
        db_pool: "Any | None" = None,
    ) -> None:
        self._model_router = model_router
        self._task_store = task_store
        self._approval_manager = approval_manager
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._hard_timeout_s = hard_timeout_s
        self._critic = critic
        self._db_pool = db_pool

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
        # ── D.1: valida tools declaradas ANTES de criar o child_task ──────────
        # Se tools_required não-vazio (source=declared) e alguma tool está ausente
        # do registry builtin, falha imediatamente com MissingRequiredTool.
        # Isso não trava a missão — o loop.py trata e marca o step como
        # 'failed_missing_tool' para continuar os outros steps.
        missing = _validate_context_tools(context)
        if missing:
            step_id = (context.channel_ref or {}).get("step_id") or context.parent_task_id
            log.warning(
                "subagent.missing_required_tool",
                missing=missing,
                step_id=step_id,
                declared=context.tools_required,
            )
            raise MissingRequiredTool(missing=missing, step_id=step_id)

        child_task = Task(
            content=context.task,
            source=TaskSource.SUBAGENT,
            parent_id=parent_task.id,
            channel_target=parent_task.channel_target,
            channel_ref=parent_task.channel_ref,
        )
        await self._task_store.create(child_task)
        await self._task_store.update_status(child_task.id, TaskStatus.RUNNING)

        # D.4.1: propaga critic e mission_id para que AIAgent._execute_tools
        # possa interceptar tools irreversíveis e registrar avaliações no Critic.
        _mission_id_str = context.mission_id or (context.channel_ref or {}).get("mission_id")
        _mission_id = None
        if _mission_id_str:
            from uuid import UUID as _UUID
            try:
                _mission_id = _UUID(_mission_id_str)
            except (ValueError, AttributeError):
                pass

        agent = build_subagent(
            context,
            self._model_router,
            critic=self._critic,
            mission_id=_mission_id,
            db_pool=self._db_pool,
        )
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
                tools_used=[],  # timeout — nenhuma tool confirmada como executada
                duration_ms=duration_ms,
                success=False,
                summary="timeout",
                verdict="exception",
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

        # Analisa execução real (tool calls) vs prosa.
        # allow_planning=True: subagentes podem retornar intent="planning" como
        # saída válida — o orquestrador pai decide o próximo passo.
        analysis = analyze_turn(result, allow_planning=True)
        tools_called = [tc.tool_name for tc in result.tool_calls_made]
        executed = analysis.verdict in (ExecutionVerdict.EXECUTED, ExecutionVerdict.INTENT_PLANNING)

        # success = DONE no task store (sem approval pendente) E houve execução real
        task_status = TaskStatus.DONE if not result.approval_request else TaskStatus.FAILED
        await self._task_store.update_status(
            child_task.id,
            task_status,
            iterations=result.iterations,
            tokens_in=result.total_input_tokens,
            tokens_out=result.total_output_tokens,
        )
        await self._task_store.record_subagent_run(
            task_id=child_task.id,
            parent_task=parent_task.id,
            tools_used=tools_called,          # tools EFETIVAMENTE chamadas
            duration_ms=duration_ms,
            success=(task_status == TaskStatus.DONE and executed),
            summary=result.final_text[:500] if result.final_text else "",
            raw_trace={
                "iterations": result.iterations,
                "cost_usd": result.estimated_cost_usd,
                "tool_call_count": analysis.tool_call_count,
            },
            verdict=analysis.verdict.value,   # "executed", "prose_only", etc.
        )

        log.info(
            "subagent.finished",
            child_id=str(child_task.id),
            success=(task_status == TaskStatus.DONE and executed),
            verdict=analysis.verdict.value,
            tool_calls=analysis.tool_call_count,
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
