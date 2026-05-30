"""Integration test D.4: missão com step irreversível → blocked_by_critic."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AgentResult, ToolCallSummary
from agent.critic.critic import CriticVerdict, PersonaVerdict
from agent.missions.executor import MissionExecutor
from agent.missions.store import MissionStep


def _make_reject_verdict() -> CriticVerdict:
    persona = PersonaVerdict(approve=False, confidence=0.95, reasoning="Irreversível", concerns=["delete"])
    return CriticVerdict(
        verdict="reject",
        mitigations=[],
        reasoning="Critic rejeitou operação de delete irreversível",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": "reject"},
    )


def _make_result_critic_blocked() -> AgentResult:
    """AgentResult simulando execução onde o Critic bloqueou uma tool."""
    return AgentResult(
        final_text="Não foi possível executar: bloqueado pelo Critic",
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=20,
        estimated_cost_usd=0.001,
        duration_s=0.1,
        tool_calls_made=[
            ToolCallSummary(tool_name="exec_sandbox", succeeded=False),
        ],
        critic_blocked=True,
        critic_blocked_tool="exec_sandbox",
        critic_blocked_reason="Critic rejeitou operação de delete irreversível",
    )


def _make_result_executed() -> AgentResult:
    """AgentResult simulando execução bem-sucedida (sem bloqueio do Critic)."""
    return AgentResult(
        final_text="Arquivo criado com sucesso",
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=30,
        estimated_cost_usd=0.001,
        duration_s=0.2,
        tool_calls_made=[
            ToolCallSummary(tool_name="write_file", succeeded=True),
        ],
        critic_blocked=False,
    )


@pytest.mark.asyncio
async def test_mission_step_blocked_by_critic_does_not_halt_mission() -> None:
    """
    Integration: step com tool irreversível → blocked_by_critic.
    Verifica: step marcado, exec_tool NÃO chamado (mock retorna critic_blocked=True),
    e a missão NÃO trava (executor retorna False sem exception).
    """
    mission_id = uuid4()
    mission = MagicMock()
    mission.id = mission_id
    mission.title = "Remover /tmp/d5_test_dir"

    step = MagicMock(spec=MissionStep)
    step.id = uuid4()
    step.mission_id = mission_id
    step.description = "rm -rf /tmp/d5_test_dir"
    step.status = "pending"
    step.retry_count = 0
    step.tools_required = []  # sem tools declaradas — usa inferência

    mission_store = MagicMock()
    mission_store.update_step = AsyncMock()
    task_store = MagicMock()
    task_store.create = AsyncMock()

    # Orchestrator retorna resultado com critic_blocked=True (Critic wired no AIAgent)
    orchestrator = MagicMock()
    orchestrator.route = AsyncMock(return_value=_make_result_critic_blocked())

    executor = MissionExecutor(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        model_router=None,
        db_pool=None,
    )

    with patch("agent.missions.executor.resolve_tools_for_step") as mock_resolve, \
         patch("agent.missions.executor.log_routing_audit") as mock_audit:
        from agent.orchestrator.tool_router import ToolResolution
        mock_resolve.return_value = ToolResolution(
            tools=["exec_sandbox", "salvar_memoria", "ler_memoria"],
            source="inferred_keyword",
            audit={
                "tools_declared": [],
                "tools_inferred": ["exec_sandbox"],
                "tools_resolved": ["exec_sandbox", "salvar_memoria", "ler_memoria"],
                "inference_source": "inferred_keyword",
            },
        )
        mock_audit.return_value = None

        success, code = await executor.execute_step(mission, step)

    # Step deve ser bloqueado, não falhar com exception
    assert success is False, "Step bloqueado não é sucesso"
    assert code == "blocked_by_critic", f"Expected 'blocked_by_critic', got '{code}'"

    # update_step chamado com status correto
    calls = mission_store.update_step.call_args_list
    status_calls = [c[1]["status"] for c in calls if "status" in c[1]]
    assert "blocked_by_critic" in status_calls, (
        f"blocked_by_critic não foi passado para update_step. Chamadas: {status_calls}"
    )

    # exec_sandbox NÃO foi chamado diretamente (orchestrator mockado retornou blocked)
    # O mock de orchestrator.route foi chamado (passa tools para o agente)
    orchestrator.route.assert_called_once()

    # Executor retornou False sem levantar exception → mission pode continuar
    # (o loop vai processar o próximo step)


@pytest.mark.asyncio
async def test_reversible_step_passes_without_critic() -> None:
    """
    Integration: step reversível (write_file) não chama Critic e termina com done.
    """
    mission = MagicMock()
    mission.id = uuid4()
    mission.title = "Contar arquivos"

    step = MagicMock(spec=MissionStep)
    step.id = uuid4()
    step.mission_id = mission.id
    step.description = "Escreva a contagem de arquivos em /tmp/d4_count.txt"
    step.status = "pending"
    step.retry_count = 0
    step.tools_required = []

    mission_store = MagicMock()
    mission_store.update_step = AsyncMock()
    task_store = MagicMock()
    task_store.create = AsyncMock()

    orchestrator = MagicMock()
    orchestrator.route = AsyncMock(return_value=_make_result_executed())

    executor = MissionExecutor(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
    )

    with patch("agent.missions.executor.resolve_tools_for_step") as mock_resolve, \
         patch("agent.missions.executor.log_routing_audit"):
        from agent.orchestrator.tool_router import ToolResolution
        mock_resolve.return_value = ToolResolution(
            tools=["write_file", "salvar_memoria", "ler_memoria"],
            source="inferred_keyword",
            audit={
                "tools_declared": [],
                "tools_inferred": ["write_file"],
                "tools_resolved": ["write_file", "salvar_memoria", "ler_memoria"],
                "inference_source": "inferred_keyword",
            },
        )

        success, code = await executor.execute_step(mission, step)

    assert success is True
    assert code == "done"

    # update_step chamado com done
    calls = mission_store.update_step.call_args_list
    status_calls = [c[1]["status"] for c in calls if "status" in c[1]]
    assert "done" in status_calls
    assert "blocked_by_critic" not in status_calls
