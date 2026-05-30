"""
Integration tests D.4.1: verifica que MissionExecutor e Critic estão wired
no caminho real do server, não apenas via injeção direta em testes unit.

Estes testes pegam regressões do tipo "esqueci de wire" que os testes unit da D.4
não detectaram (MissionExecutor existia mas nunca era passado para AutonomousLoop).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.autonomous.loop import AutonomousLoop
from agent.missions.executor import MissionExecutor
from agent.missions.store import MissionStore
from agent.orchestrator.router import Orchestrator
from agent.subagents.pool import SubagentPool
from agent.tasks.store import TaskStore


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_mock_model_router() -> MagicMock:
    mr = MagicMock()
    mr.chat = AsyncMock(return_value=("STRATEGIC", None))
    return mr


def _make_mock_mission_store() -> MagicMock:
    ms = MagicMock(spec=MissionStore)
    return ms


def _make_mock_task_store() -> MagicMock:
    ts = MagicMock(spec=TaskStore)
    ts.create = AsyncMock()
    ts.update_status = AsyncMock()
    return ts


def _make_mock_orchestrator() -> MagicMock:
    orc = MagicMock(spec=Orchestrator)
    orc.route = AsyncMock()
    return orc


def _make_mock_critic() -> MagicMock:
    critic = MagicMock()
    critic.evaluate = AsyncMock()
    return critic


# ─── teste 1 ────────────────────────────────────────────────────────────────

def test_autonomous_loop_has_executor_wired() -> None:
    """
    Verifica que AutonomousLoop recebe MissionExecutor wired.

    Reproduz o padrão de server.py: cria MissionExecutor com as dependências
    corretas e passa para AutonomousLoop(executor=...).
    """
    mission_store = _make_mock_mission_store()
    task_store = _make_mock_task_store()
    orchestrator = _make_mock_orchestrator()
    model_router = _make_mock_model_router()
    critic = _make_mock_critic()

    executor = MissionExecutor(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        model_router=model_router,
        db_pool=None,
    )

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        critic=critic,
        reflector=None,
        planner=None,
        db_pool=None,
        executor=executor,
    )

    assert loop._executor is not None, "loop._executor deve ser MissionExecutor, não None"
    assert isinstance(
        loop._executor, MissionExecutor
    ), f"esperado MissionExecutor, obtido {type(loop._executor)}"


# ─── teste 2 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_receives_critic_via_pool() -> None:
    """
    Verifica que build_subagent é chamado com critic e mission_id no caminho
    STRATEGIC do SubagentPool.

    Simula o fluxo: pool._run_one → build_subagent(critic=..., mission_id=...)
    """
    from agent.subagents.context import SubAgentContext
    from agent.tasks.task import Task, TaskSource

    model_router = _make_mock_model_router()
    task_store = _make_mock_task_store()
    mock_critic = _make_mock_critic()

    pool = SubagentPool(
        model_router=model_router,
        task_store=task_store,
        critic=mock_critic,
    )

    mission_uuid = str(uuid4())
    step_uuid = str(uuid4())

    ctx = SubAgentContext(
        task="Execute algo",
        tools_allowed=["read_file"],
        channel_ref={"mission_id": mission_uuid, "step_id": step_uuid},
        mission_id=mission_uuid,
    )

    parent_task = Task(
        content="Execute algo",
        source=TaskSource.CRON,
        channel_ref={"mission_id": mission_uuid, "step_id": step_uuid},
    )
    parent_task.id = uuid4()

    captured_kwargs: dict = {}

    from agent.core import AgentResult

    def fake_build_subagent(context, model_router, critic=None, mission_id=None):
        captured_kwargs["critic"] = critic
        captured_kwargs["mission_id"] = mission_id
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=AgentResult(
                final_text="done",
                iterations=1,
                total_input_tokens=10,
                total_output_tokens=10,
                estimated_cost_usd=0.0,
                duration_s=0.1,
            )
        )
        return agent

    with patch("agent.subagents.pool.build_subagent", side_effect=fake_build_subagent):
        # task_store.create precisa retornar algo válido
        task_store.create = AsyncMock()
        task_store.update_status = AsyncMock()
        task_store.record_subagent_run = AsyncMock()

        await pool.spawn(ctx, parent_task)

    assert captured_kwargs.get("critic") is mock_critic, (
        f"build_subagent deve receber critic=mock_critic, obtido: {captured_kwargs.get('critic')}"
    )
    assert captured_kwargs.get("mission_id") is not None, (
        "build_subagent deve receber mission_id != None quando channel_ref tem mission_id"
    )
    from uuid import UUID
    assert str(captured_kwargs["mission_id"]) == mission_uuid, (
        f"mission_id deve ser UUID do channel_ref ({mission_uuid}), "
        f"obtido: {captured_kwargs['mission_id']}"
    )
