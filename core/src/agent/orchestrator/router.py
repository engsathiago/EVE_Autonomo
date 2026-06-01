"""
Orchestrator: decide tier e executa a tarefa da forma correta.

Integração sem quebrar Fase 5:
- Se orchestrator não estiver inicializado, server.py continua usando AIAgent diretamente.
- Os endpoints existentes (/api/chat, /v1/messages) chamam orchestrator.route(task) em vez
  de AIAgent.run() — o orchestrator chama o AIAgent internamente para INSTANT/FAST.

Fase 8: lint de steps rejeita padrões proibidos (subprocess/os.system/eval/exec builtin).
Use exec_tool (agent.tools.exec_tool) para toda execução de comandos arbitrários.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

# Padrões proibidos em código de steps — devem usar exec_tool em vez disso.
_FORBIDDEN_PATTERNS = re.compile(
    r"\bsubprocess\s*\.\s*(run|Popen|call|check_output|check_call)\b"
    r"|\bos\s*\.\s*system\s*\("
    r"|\beval\s*\("
    r"|\bexec\s*\("
)

from agent.core import AgentResult, AIAgent
from agent.observability.logger import get_logger
from agent.orchestrator.aggregator import merge
from agent.orchestrator.tiers import ExecutionTier, TierClassifier
from agent.tasks.task import Task, TaskStatus
from agent.tools.registry import ToolRegistry, register_builtin, register_memory_tools

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager
    from agent.memory.compressor import ContextCompressor
    from agent.memory.curator import Curator
    from agent.memory.store import MemoryStore
    from agent.models.router import ModelRouter
    from agent.skills.manager import SkillManager
    from agent.subagents.pool import SubagentPool
    from agent.tasks.store import TaskStore

log = get_logger(__name__)


class Orchestrator:
    def __init__(
        self,
        model_router: ModelRouter,
        task_store: TaskStore,
        subagent_pool: SubagentPool,
        classifier: TierClassifier,
        memory_store: MemoryStore | None = None,
        curator: Curator | None = None,
        compressor: ContextCompressor | None = None,
        skill_manager: SkillManager | None = None,
        approval_manager: ApprovalManager | None = None,
        fast_max_iterations: int = 3,
        strategic_max_iterations: int = 8,
        epic_max_parallel: int = 4,
        epic_max_iterations_per_child: int = 6,
        # D.1: pool para gravar auditoria em step_tool_routing (opcional)
        db_pool: Any | None = None,
    ) -> None:
        self._model_router = model_router
        self._task_store = task_store
        self._subagent_pool = subagent_pool
        self._classifier = classifier
        self._memory_store = memory_store
        self._curator = curator
        self._compressor = compressor
        self._skill_manager = skill_manager
        self._approval_manager = approval_manager
        self._fast_max_iter = fast_max_iterations
        self._strategic_max_iter = strategic_max_iterations
        self._epic_max_parallel = epic_max_parallel
        self._epic_max_iter_child = epic_max_iterations_per_child
        self._db_pool = db_pool  # D.1: para log_routing_audit
        # Contadores para stats (em memória, 24h rolling)
        self._stats: dict[str, list[float]] = defaultdict(list)

    async def route(self, task: Task) -> AgentResult:
        """Ponto de entrada principal. Classifica e executa a task."""
        await self._task_store.update_status(task.id, TaskStatus.RUNNING)
        t0 = time.monotonic()

        try:
            tier = await self._classifier.classify(task.content)
            task.tier = tier.value
            await self._task_store.update_status(task.id, TaskStatus.RUNNING, tier=tier.value)

            result = await self._dispatch(task, tier)

            duration = time.monotonic() - t0
            self._record_stat(tier, duration)

            await self._task_store.update_status(
                task.id,
                TaskStatus.DONE,
                result={"text": result.final_text[:2000]} if result.final_text else None,
                iterations=result.iterations,
                tokens_in=result.total_input_tokens,
                tokens_out=result.total_output_tokens,
                tier=tier.value,
            )
            return result

        except Exception as exc:
            await self._task_store.update_status(task.id, TaskStatus.FAILED, error=str(exc))
            raise

    async def _dispatch(self, task: Task, tier: ExecutionTier) -> AgentResult:
        if tier == ExecutionTier.INSTANT:
            return await self._run_inline(task, max_iterations=1)
        elif tier == ExecutionTier.FAST:
            return await self._run_inline(task, max_iterations=self._fast_max_iter)
        elif tier == ExecutionTier.STRATEGIC:
            return await self._run_strategic(task)
        else:  # EPIC
            return await self._run_epic(task)

    async def _run_inline(self, task: Task, max_iterations: int) -> AgentResult:
        """INSTANT/FAST: pai executa diretamente, sem subagente."""
        from uuid import uuid4

        from agent.config import AgentSettings, get_settings
        from agent.transports.anthropic import AnthropicTransport

        settings = get_settings()
        registry = self._build_registry(task)
        # Fallback inerte: AIAgent prefere self._model_router quando presente (core.py:_chat).
        # Este transport só é usado se model_router=None — não é o caminho ativo em produção.
        transport = AnthropicTransport(model=settings.anthropic.planner_model)

        # Reutiliza conversation_id do canal de origem quando disponível;
        # caso contrário cria nova conversa no banco para evitar FK violation.
        conv_id_str = (task.channel_ref or {}).get("conversation_id")
        if conv_id_str:
            conversation_id = UUID(conv_id_str)
        elif self._memory_store is not None:
            conversation_id = await self._memory_store.create_conversation()
        else:
            conversation_id = uuid4()

        agent_settings = AgentSettings(
            max_iterations=max_iterations,
            reflection_every=999,
        )
        agent = AIAgent(
            transport=transport,
            tool_registry=registry,
            settings=agent_settings,
            memory_store=self._memory_store,
            curator=self._curator,
            compressor=self._compressor,
            conversation_id=conversation_id,
            skill_manager=self._skill_manager,
            model_router=self._model_router,
        )
        return await agent.run(goal=task.content, conversation_history=[])

    async def _run_strategic(self, task: Task) -> AgentResult:
        """STRATEGIC: 1 subagente sequencial com tools resolvidas dinamicamente."""
        from agent.orchestrator.tool_router import (
            StepSpec,
            log_routing_audit,
            resolve_tools_for_step,
        )
        from agent.subagents.context import SubAgentContext

        step_spec = StepSpec(
            description=task.content,
            tools_required=task.tools_required,
        )
        resolution = await resolve_tools_for_step(
            step_spec,
            ExecutionTier.STRATEGIC,
            model_router=self._model_router,
        )

        # Audit: registra no banco se temos pool e step_id
        step_id_str = (task.channel_ref or {}).get("step_id")
        if step_id_str and self._db_pool is not None:
            from uuid import UUID as _UUID
            try:
                await log_routing_audit(
                    step_id=_UUID(step_id_str),
                    tier=ExecutionTier.STRATEGIC.value,
                    resolution=resolution,
                    db_pool=self._db_pool,
                )
            except Exception as exc:
                log.warning("orchestrator.routing_audit.failed", error=str(exc))

        ctx = SubAgentContext(
            task=task.content,
            tools_allowed=resolution.tools,
            # tools_required só é preenchido quando source=declared para pool validar
            tools_required=(step_spec.tools_required if resolution.source == "declared" else []),
            max_iterations=self._strategic_max_iter,
            timeout_s=120,
            channel_ref=task.channel_ref,
            parent_task_id=str(task.id),
        )
        log.info(
            "orchestrator.strategic.tools_resolved",
            source=resolution.source,
            tools=resolution.tools,
            task_id=str(task.id),
        )
        return await self._subagent_pool.spawn(ctx, task)

    async def _run_epic(self, task: Task) -> AgentResult:
        """
        EPIC: planner divide em N subtasks → N subagentes paralelos → aggregator.

        O planner usa LLM para decompor a tarefa. Se a decomposição falhar,
        fallback para STRATEGIC (1 subagente com a tarefa completa).
        """
        subtasks = await self._plan_epic(task.content)
        if not subtasks:
            log.warning("orchestrator.epic.plan_failed", fallback="strategic")
            return await self._run_strategic(task)

        from agent.orchestrator.tool_router import StepSpec, resolve_tools_for_step
        from agent.subagents.context import SubAgentContext

        contexts = []
        for st in subtasks[: self._epic_max_parallel]:
            # Cada sub-task do EPIC resolve suas próprias tools dinamicamente.
            # tools_required=[] pois EPIC vem de decomposição automática (sem declaração).
            sub_spec = StepSpec(description=st, tools_required=[])
            sub_resolution = await resolve_tools_for_step(
                sub_spec,
                ExecutionTier.EPIC,
                model_router=self._model_router,
            )
            contexts.append(
                SubAgentContext(
                    task=st,
                    tools_allowed=sub_resolution.tools,
                    tools_required=[],  # EPIC = inferido, sem validação de declared
                    max_iterations=self._epic_max_iter_child,
                    timeout_s=120,
                    channel_ref=task.channel_ref,
                    parent_task_id=str(task.id),
                )
            )

        results = await self._subagent_pool.spawn_parallel(contexts, task)
        return merge(results, parent_content=task.content)

    async def _plan_epic(self, content: str) -> list[str]:
        """Usa LLM para decompor tarefa EPIC em subtasks independentes."""
        import json as _json

        prompt = (
            "Decompose this task into independent parallel subtasks (max 4).\n"
            "Return ONLY a JSON array of strings, each a self-contained subtask.\n"
            "If the task cannot be parallelized, return an empty array [].\n\n"
            f"Task: {content}"
        )
        try:
            response = await self._model_router.chat(
                system="You decompose tasks. Reply only with a JSON array.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            raw = response.text.strip()
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1:
                subtasks: list[str] = _json.loads(raw[start : end + 1])
                return [s for s in subtasks if isinstance(s, str) and s.strip()]
        except Exception as exc:
            log.warning("orchestrator.epic.plan_error", error=str(exc))
        return []

    def _build_registry(self, task: Task) -> ToolRegistry:
        registry = ToolRegistry()
        register_builtin(registry)
        if self._memory_store:
            register_memory_tools(registry, self._memory_store, task.id)
        return registry

    def _record_stat(self, tier: ExecutionTier, duration_s: float) -> None:
        cutoff = time.monotonic() - 86400  # 24h
        key = tier.value
        self._stats[key] = [t for t in self._stats[key] if t > cutoff]
        self._stats[key].append(duration_s)

    def check_step_safety(self, step_code: str) -> list[str]:
        """
        Verifica se o código de um step usa padrões proibidos de execução direta.
        Retorna lista de violações (vazia = step seguro).

        Padrões bloqueados: subprocess.run/Popen/call/check_output, os.system, eval(), exec().
        Use exec_tool (agent.tools.exec_tool) em vez de qualquer um desses.
        """
        violations = []
        for match in _FORBIDDEN_PATTERNS.finditer(step_code):
            violations.append(
                f"Padrão proibido '{match.group()}' na posição {match.start()} — "
                "use exec_tool (agent.tools.exec_tool) para execução de comandos"
            )
        return violations

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for tier in ExecutionTier:
            durations = self._stats.get(tier.value, [])
            if durations:
                sorted_d = sorted(durations)
                n = len(sorted_d)
                result[tier.value] = {
                    "count_24h": n,
                    "p50_s": round(sorted_d[n // 2], 3),
                    "p95_s": round(sorted_d[int(n * 0.95)], 3),
                }
            else:
                result[tier.value] = {"count_24h": 0, "p50_s": 0.0, "p95_s": 0.0}
        return result
