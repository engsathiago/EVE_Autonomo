"""Testa SubagentPool — spawn, timeout, cancel e paralelismo."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core import AgentResult
from agent.subagents.context import SubAgentContext
from agent.subagents.pool import SubagentPool
from agent.tasks.task import Task, TaskSource


def _make_pool(hard_timeout: int = 300) -> SubagentPool:
    pool = SubagentPool(
        model_router=MagicMock(),
        task_store=_mock_task_store(),
        approval_manager=None,
        max_concurrent=4,
        hard_timeout_s=hard_timeout,
    )
    return pool


def _mock_task_store() -> MagicMock:
    store = MagicMock()
    store.create = AsyncMock()
    store.update_status = AsyncMock()
    store.record_subagent_run = AsyncMock()
    return store


def _success_result() -> AgentResult:
    return AgentResult(
        final_text="resultado",
        iterations=2,
        total_input_tokens=100,
        total_output_tokens=50,
        estimated_cost_usd=0.001,
        duration_s=1.5,
    )


def _parent_task() -> Task:
    return Task(
        content="tarefa pai",
        source=TaskSource.CLI,
        channel_ref={"source": "cli"},
    )


@pytest.mark.asyncio
async def test_spawn_returns_result() -> None:
    pool = _make_pool()
    ctx = SubAgentContext(task="subtarefa", tools_allowed=[])

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=_success_result())
        mock_build.return_value = mock_agent

        result = await pool.spawn(ctx, _parent_task())

    assert result.final_text == "resultado"
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_spawn_timeout_returns_error_result() -> None:
    """Timeout retorna AgentResult com error='timeout', não lança exceção."""
    pool = _make_pool(hard_timeout=1)
    ctx = SubAgentContext(task="subtarefa lenta", tools_allowed=[], timeout_s=1)

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()

        async def _slow(*args, **kwargs):  # type: ignore[no-untyped-def]
            await asyncio.sleep(10)
            return _success_result()

        mock_agent.run = _slow
        mock_build.return_value = mock_agent

        result = await pool.spawn(ctx, _parent_task())

    assert result.approval_request is not None
    assert result.approval_request.get("error") == "timeout"


@pytest.mark.asyncio
async def test_spawn_parallel_creates_multiple_subagents() -> None:
    """spawn_parallel cria N subagentes e retorna N resultados."""
    pool = _make_pool()
    contexts = [SubAgentContext(task=f"subtarefa {i}", tools_allowed=[]) for i in range(3)]

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=_success_result())
        mock_build.return_value = mock_agent

        results = await pool.spawn_parallel(contexts, _parent_task())

    assert len(results) == 3
    assert mock_build.call_count == 3


@pytest.mark.asyncio
async def test_spawn_records_subagent_run() -> None:
    """Resultado de cada spawn é registrado no TaskStore."""
    pool = _make_pool()
    ctx = SubAgentContext(task="subtarefa", tools_allowed=["web_search"])

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=_success_result())
        mock_build.return_value = mock_agent

        await pool.spawn(ctx, _parent_task())

    pool._task_store.record_subagent_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency() -> None:
    """max_concurrent=1: nunca mais que 1 subagente simultâneo."""
    pool = SubagentPool(
        model_router=MagicMock(),
        task_store=_mock_task_store(),
        max_concurrent=1,
        hard_timeout_s=30,
    )
    active: list[int] = []
    max_active = [0]

    async def _track(*args: object, **kwargs: object) -> AgentResult:
        active.append(1)
        max_active[0] = max(max_active[0], len(active))
        await asyncio.sleep(0.02)
        active.pop()
        return _success_result()

    contexts = [SubAgentContext(task=f"t{i}", tools_allowed=[]) for i in range(3)]

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()
        mock_agent.run = _track
        mock_build.return_value = mock_agent
        await pool.spawn_parallel(contexts, _parent_task())

    assert max_active[0] == 1, f"Esperado máximo 1 ativo, obteve {max_active[0]}"
