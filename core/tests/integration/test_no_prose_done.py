"""
B.4 — Testes de regressão: nenhum step é marcado 'done' sem execução real.

Regra: se esse teste falhar, NÃO mergeia. O bug voltou.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AgentResult, ToolCallSummary
from agent.missions.store import MissionStep
from agent.subagents.context import SubAgentContext
from agent.subagents.pool import SubagentPool
from agent.tasks.task import Task, TaskSource


# ---------------------------------------------------------------------------
# Helpers compartilhados
# ---------------------------------------------------------------------------


def _make_mission(mission_id=None):
    m = MagicMock()
    m.id = mission_id or uuid4()
    m.title = "Missão de regressão"
    m.status = "active"
    from datetime import datetime, timezone
    m.updated_at = datetime.now(tz=timezone.utc)
    return m


def _make_step(seq=0, retry_count=0):
    s = MagicMock(spec=MissionStep)
    s.id = uuid4()
    s.sequence = seq
    s.description = f"Step {seq}"
    s.status = "pending"
    s.retry_count = retry_count
    # D.1: campo adicionado em migration 016; [] = inferência automática de tools
    s.tools_required = []
    return s


def _make_prose_result() -> AgentResult:
    """AgentResult sem tool calls — simula resposta em prosa."""
    return AgentResult(
        final_text="Não tenho acesso ao filesystem para realizar essa tarefa.",
        iterations=1,
        total_input_tokens=40,
        total_output_tokens=20,
        estimated_cost_usd=0.001,
        duration_s=0.3,
        tool_calls_made=[],  # sem tool calls
    )


def _make_executed_result(tool_name: str = "read_file", succeeded: bool = True) -> AgentResult:
    """AgentResult com ao menos 1 tool call — simula execução real."""
    return AgentResult(
        final_text="Arquivo lido com sucesso.",
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=30,
        estimated_cost_usd=0.001,
        duration_s=0.5,
        tool_calls_made=[
            ToolCallSummary(tool_name=tool_name, succeeded=succeeded),
        ],
    )


def _make_loop(result: AgentResult, step: MissionStep | None = None, mission=None):
    """Cria AutonomousLoop totalmente mockado com orchestrator configurável."""
    from agent.autonomous.loop import AutonomousLoop

    mission_store = MagicMock()
    orchestrator = MagicMock()
    task_store = MagicMock()

    _mission = mission or _make_mission()
    _step = step or _make_step()

    mission_store.list_active = AsyncMock(return_value=[_mission])
    mission_store.get_pending_steps = AsyncMock(return_value=[_step])
    mission_store.get_all_steps = AsyncMock(return_value=[_step])
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock()

    task_store.create = AsyncMock()

    orchestrator.route = AsyncMock(return_value=result)

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
    )
    return loop, _step


def _make_pool_and_task():
    """Cria SubagentPool + parent Task para testes de subagente."""
    task_store = MagicMock()
    task_store.create = AsyncMock()
    task_store.update_status = AsyncMock()
    task_store.record_subagent_run = AsyncMock()

    model_router = MagicMock()

    pool = SubagentPool(
        model_router=model_router,
        task_store=task_store,
        approval_manager=None,
        hard_timeout_s=60,
    )

    parent_task = Task(
        content="tarefa pai",
        source=TaskSource.CLI,
        channel_ref={"source": "cli"},
    )

    ctx = SubAgentContext(task="subtarefa de teste", tools_allowed=["read_file"])

    return pool, parent_task, ctx, task_store


# ---------------------------------------------------------------------------
# Caso 1 — prosa pura → status="failed_no_execution", verdict="prose_only"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prose_only_never_marks_done() -> None:
    """Loop marca 'failed_no_execution' quando LLM retorna só prosa."""
    prose = _make_prose_result()
    loop, step = _make_loop(prose)

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    # Nenhum step pode ser marcado done
    assert report.steps_dispatched == 0, "Prosa não deve contar como step executado"

    call_kwargs = loop._mission_store.update_step.call_args.kwargs
    assert call_kwargs["status"] == "failed_no_execution", (
        f"Status deveria ser 'failed_no_execution', recebeu: {call_kwargs['status']}"
    )
    assert call_kwargs["result"]["verdict"] == "prose_only", (
        f"Verdict deveria ser 'prose_only', recebeu: {call_kwargs['result']['verdict']}"
    )


# ---------------------------------------------------------------------------
# Caso 2 — tool call real → status="done", tools_invoked=["read_file"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_tool_call_marks_done() -> None:
    """Loop marca 'done' com tools_invoked preenchido quando há tool call."""
    executed = _make_executed_result(tool_name="read_file")
    loop, step = _make_loop(executed)

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    assert report.steps_dispatched == 1, "Deve contar 1 step executado"

    call_kwargs = loop._mission_store.update_step.call_args.kwargs
    assert call_kwargs["status"] == "done", (
        f"Status deveria ser 'done', recebeu: {call_kwargs['status']}"
    )
    assert call_kwargs["result"]["tools_invoked"] == ["read_file"], (
        f"tools_invoked errado: {call_kwargs['result']['tools_invoked']}"
    )
    assert call_kwargs["result"]["verdict"] == "executed"


# ---------------------------------------------------------------------------
# Caso 3 — mix prosa + tool call → status="done" (tool call prevalece)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mix_prose_and_tool_marks_done() -> None:
    """AgentResult com texto E tool call → step marcado done (tool call prevalece)."""
    mixed = AgentResult(
        final_text="Executei a leitura: conteúdo encontrado.",
        iterations=2,
        total_input_tokens=80,
        total_output_tokens=60,
        estimated_cost_usd=0.002,
        duration_s=1.0,
        tool_calls_made=[
            ToolCallSummary(tool_name="read_file", succeeded=True),
        ],
    )
    loop, step = _make_loop(mixed)

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    assert report.steps_dispatched == 1

    call_kwargs = loop._mission_store.update_step.call_args.kwargs
    assert call_kwargs["status"] == "done"
    assert call_kwargs["result"]["verdict"] == "executed"


# ---------------------------------------------------------------------------
# Caso 4 — subagente com intent="planning", zero tools → success=True, verdict="intent_planning"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_planning_intent_counts_as_success() -> None:
    """Subagente com intent='planning' (sem tool calls) → success=True, verdict='intent_planning'."""
    planning_result = AgentResult(
        final_text="Plano elaborado: vou executar em 3 etapas.",
        iterations=1,
        total_input_tokens=30,
        total_output_tokens=50,
        estimated_cost_usd=0.001,
        duration_s=0.4,
        tool_calls_made=[],
        intent="planning",
    )

    pool, parent_task, ctx, task_store = _make_pool_and_task()

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=planning_result)

    with patch("agent.subagents.pool.build_subagent", return_value=mock_agent):
        await pool.spawn(ctx, parent_task)

    record_kwargs = task_store.record_subagent_run.call_args.kwargs
    assert record_kwargs["success"] is True, (
        f"success deveria ser True para planning intent, recebeu: {record_kwargs['success']}"
    )
    assert record_kwargs["verdict"] == "intent_planning", (
        f"verdict deveria ser 'intent_planning', recebeu: {record_kwargs['verdict']}"
    )
    assert record_kwargs["tools_used"] == [], (
        f"tools_used deveria ser vazio, recebeu: {record_kwargs['tools_used']}"
    )


# ---------------------------------------------------------------------------
# Caso 5 — subagente sem intent + zero tools → success=False, verdict="prose_only"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subagent_no_intent_no_tools_fails() -> None:
    """Subagente sem intent e sem tool calls → success=False, verdict='prose_only'."""
    prose_result = AgentResult(
        final_text="Não consegui executar nenhuma ação relevante.",
        iterations=1,
        total_input_tokens=25,
        total_output_tokens=40,
        estimated_cost_usd=0.001,
        duration_s=0.3,
        tool_calls_made=[],
        intent=None,
    )

    pool, parent_task, ctx, task_store = _make_pool_and_task()

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=prose_result)

    with patch("agent.subagents.pool.build_subagent", return_value=mock_agent):
        await pool.spawn(ctx, parent_task)

    record_kwargs = task_store.record_subagent_run.call_args.kwargs
    assert record_kwargs["success"] is False, (
        f"success deveria ser False para prosa sem tool call, recebeu: {record_kwargs['success']}"
    )
    assert record_kwargs["verdict"] == "prose_only", (
        f"verdict deveria ser 'prose_only', recebeu: {record_kwargs['verdict']}"
    )
    assert record_kwargs["tools_used"] == [], (
        f"tools_used deveria ser vazio, recebeu: {record_kwargs['tools_used']}"
    )


# ---------------------------------------------------------------------------
# Caso 6 — tool call com succeeded=False ainda conta como EXECUTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_tool_call_still_counts_as_executed() -> None:
    """Tool call que lançou erro interno (succeeded=False) ainda é execução real."""
    failed_tool_result = AgentResult(
        final_text="Tentei ler o arquivo mas obtive erro de permissão.",
        iterations=1,
        total_input_tokens=45,
        total_output_tokens=25,
        estimated_cost_usd=0.001,
        duration_s=0.6,
        tool_calls_made=[
            ToolCallSummary(tool_name="read_file", succeeded=False),
        ],
    )
    loop, step = _make_loop(failed_tool_result)

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    # Tool call aconteceu — mesmo com erro, é execução (não prosa)
    assert report.steps_dispatched == 1, (
        "Tool call com erro ainda deve contar como step executado"
    )

    call_kwargs = loop._mission_store.update_step.call_args.kwargs
    assert call_kwargs["status"] == "done", (
        f"Status deveria ser 'done', recebeu: {call_kwargs['status']}"
    )
    assert call_kwargs["result"]["tool_call_count"] == 1, (
        f"tool_call_count deveria ser 1, recebeu: {call_kwargs['result']['tool_call_count']}"
    )
    assert call_kwargs["result"]["verdict"] == "executed"
