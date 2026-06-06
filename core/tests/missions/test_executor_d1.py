"""D.1 no MissionExecutor: resolve tools antes de spawn, grava step_tool_routing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AgentResult, ToolCallSummary
from agent.missions.executor import MissionExecutor
from agent.missions.store import MissionStep


def _make_step(
    description: str = "Buscar informações",
    tools_required: list[str] | None = None,
) -> MissionStep:
    s = MagicMock(spec=MissionStep)
    s.id = uuid4()
    s.mission_id = uuid4()
    s.description = description
    s.status = "pending"
    s.retry_count = 0
    s.tools_required = tools_required or []
    return s


def _make_mission(mission_id=None) -> MagicMock:
    m = MagicMock()
    m.id = mission_id or uuid4()
    m.title = "Missão de teste"
    return m


def _make_executed_result() -> AgentResult:
    return AgentResult(
        final_text="ok",
        iterations=1,
        total_input_tokens=10,
        total_output_tokens=10,
        estimated_cost_usd=0.001,
        duration_s=0.1,
        tool_calls_made=[ToolCallSummary(tool_name="web_search", succeeded=True)],
        critic_blocked=False,
    )


def _make_executor(orchestrator_result=None) -> tuple[MissionExecutor, MagicMock, MagicMock]:
    mission_store = MagicMock()
    mission_store.update_step = AsyncMock()

    task_store = MagicMock()
    task_store.create = AsyncMock()

    orchestrator = MagicMock()
    orchestrator.route = AsyncMock(
        return_value=orchestrator_result or _make_executed_result()
    )

    executor = MissionExecutor(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        model_router=None,
        db_pool=None,
    )
    return executor, mission_store, task_store


@pytest.mark.asyncio
async def test_mission_step_resolves_tools_via_router() -> None:
    """D.1: execute_step chama resolve_tools_for_step antes do spawn."""
    executor, mission_store, task_store = _make_executor()
    mission = _make_mission()
    step = _make_step(description="buscar na web sobre AI")

    with patch(
        "agent.missions.executor.resolve_tools_for_step"
    ) as mock_resolve:
        from agent.orchestrator.tool_router import ToolResolution
        mock_resolve.return_value = ToolResolution(
            tools=["web_search", "salvar_memoria", "ler_memoria"],
            source="inferred_keyword",
            audit={
                "tools_declared": [],
                "tools_inferred": ["web_search"],
                "tools_resolved": ["web_search", "salvar_memoria", "ler_memoria"],
                "inference_source": "inferred_keyword",
            },
        )
        with patch("agent.missions.executor.log_routing_audit") as mock_audit:
            mock_audit.return_value = None

            success, code = await executor.execute_step(mission, step)

    assert mock_resolve.called, "resolve_tools_for_step deve ser chamado antes do spawn"
    assert success is True
    assert code == "done"


@pytest.mark.asyncio
async def test_mission_step_failed_missing_tool_when_tool_absent() -> None:
    """D.1: step com tool declarada ausente deve ser marcado como failed_missing_tool."""
    executor, mission_store, task_store = _make_executor()
    mission = _make_mission()
    step = _make_step(
        description="executar ferramenta especial",
        tools_required=["tool_que_nao_existe"],
    )

    with patch(
        "agent.missions.executor.resolve_tools_for_step"
    ) as mock_resolve, patch(
        "agent.missions.executor.validate_declared_tools"
    ) as mock_validate, patch(
        "agent.missions.executor.log_routing_audit"
    ) as mock_audit:
        from agent.orchestrator.tool_router import ToolResolution
        mock_resolve.return_value = ToolResolution(
            tools=["tool_que_nao_existe", "salvar_memoria", "ler_memoria"],
            source="declared",
            audit={
                "tools_declared": ["tool_que_nao_existe"],
                "tools_inferred": [],
                "tools_resolved": ["tool_que_nao_existe", "salvar_memoria", "ler_memoria"],
                "inference_source": "declared",
            },
            tools_declared=["tool_que_nao_existe"],
        )
        mock_validate.return_value = ["tool_que_nao_existe"]  # ausente do registry
        mock_audit.return_value = None

        success, code = await executor.execute_step(mission, step)

    assert success is False
    assert code == "failed_missing_tool"

    # Verifica que update_step foi chamado com o status correto
    mission_store.update_step.assert_called_once()
    call_kwargs = mission_store.update_step.call_args[1]
    assert call_kwargs["status"] == "failed_missing_tool"
    assert "tool_que_nao_existe" in call_kwargs["error"]

    # Verifica que task_store.create NÃO foi chamado (falhou antes do spawn)
    task_store.create.assert_not_called()
