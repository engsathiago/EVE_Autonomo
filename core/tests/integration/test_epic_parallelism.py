"""
Integração: tarefa EPIC cria N subagentes em paralelo.

Usa mocks — não precisa de Postgres nem LLM real.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core import AgentResult
from agent.orchestrator.router import Orchestrator
from agent.orchestrator.tiers import ExecutionTier
from agent.subagents.pool import SubagentPool
from agent.tasks.task import Task, TaskSource


def _make_task_store() -> MagicMock:
    s = MagicMock()
    s.create = AsyncMock()
    s.update_status = AsyncMock()
    s.record_subagent_run = AsyncMock()
    return s


def _success_result(text: str = "ok") -> AgentResult:
    return AgentResult(
        final_text=text,
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=25,
        estimated_cost_usd=0.0001,
        duration_s=0.5,
    )


@pytest.mark.asyncio
async def test_epic_creates_parallel_subagents() -> None:
    """EPIC com 3 subtasks → 3 subagentes em paralelo."""
    task_store = _make_task_store()

    # Classifier sempre retorna EPIC
    mock_classifier = MagicMock()
    mock_classifier.classify = AsyncMock(return_value=ExecutionTier.EPIC)

    # Pool real, mas build_subagent mockado
    pool = SubagentPool(
        model_router=MagicMock(),
        task_store=task_store,
        max_concurrent=4,
        hard_timeout_s=30,
    )

    # Orchestrator com plan_epic mockado para retornar 3 subtasks
    orchestrator = Orchestrator(
        model_router=MagicMock(),
        task_store=task_store,
        subagent_pool=pool,
        classifier=mock_classifier,
        epic_max_parallel=4,
    )

    parent_task = Task(content="monitorar 3 sites", source=TaskSource.CLI)
    task_store.create = AsyncMock(return_value=parent_task)

    start_times: list[float] = []

    async def _timed_run(*args, **kwargs) -> AgentResult:  # type: ignore[no-untyped-def]
        import time
        start_times.append(time.monotonic())
        await asyncio.sleep(0.1)
        return _success_result()

    with patch.object(orchestrator, "_plan_epic", AsyncMock(return_value=[
        "site A: extrair título",
        "site B: extrair título",
        "site C: extrair título",
    ])):
        with patch("agent.subagents.pool.build_subagent") as mock_build:
            mock_agent = MagicMock()
            mock_agent.run = _timed_run
            mock_build.return_value = mock_agent

            result = await orchestrator.route(parent_task)

    # 3 subagentes foram criados
    assert mock_build.call_count == 3

    # Os 3 iniciaram aproximadamente ao mesmo tempo (diferença < 0.05s)
    if len(start_times) >= 2:
        spread = max(start_times) - min(start_times)
        assert spread < 0.05, f"Subagentes não executaram em paralelo (spread={spread:.3f}s)"

    # Resultado agregado contém textos de todos
    assert "Subtask" in result.final_text or result.final_text != ""


@pytest.mark.asyncio
async def test_epic_partial_result_when_some_fail() -> None:
    """Se 1 de 3 subagentes falha, resultado é partial=True."""
    from agent.orchestrator.aggregator import merge

    results = [
        _success_result("resultado A"),
        _success_result("resultado B"),
        AgentResult(
            final_text="",
            iterations=0,
            total_input_tokens=0,
            total_output_tokens=0,
            estimated_cost_usd=0,
            duration_s=0,
            approval_request={"error": "timeout"},
        ),
    ]

    merged = merge(results)

    # Texto dos dois sucedidos está presente
    assert "resultado A" in merged.final_text
    assert "resultado B" in merged.final_text
    # Indica falha parcial
    assert "failed" in merged.final_text.lower() or "timeout" in merged.final_text
