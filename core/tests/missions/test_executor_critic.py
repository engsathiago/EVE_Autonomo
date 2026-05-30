"""D.4: Critic hook em AIAgent._execute_tools — tools irreversíveis são interceptadas."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AgentResult, AIAgent, ToolCallSummary
from agent.critic.critic import CriticVerdict, PersonaVerdict


def _make_reject_verdict() -> CriticVerdict:
    persona = PersonaVerdict(
        approve=False,
        confidence=0.9,
        reasoning="Operação irreversível e perigosa",
        concerns=["rm -rf pode apagar dados críticos"],
    )
    return CriticVerdict(
        verdict="reject",
        mitigations=[],
        reasoning="Critic rejeitou: operação de delete não autorizada",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": "reject"},
    )


@pytest.mark.asyncio
async def test_critic_blocks_irreversible_tool() -> None:
    """D.4: AIAgent com Critic deve bloquear tool irreversível (exec_sandbox)."""
    from agent.tools.registry import ToolRegistry

    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_make_reject_verdict())

    mission_id = uuid4()
    task_id = uuid4()

    registry = ToolRegistry()
    transport = MagicMock()
    transport.chat = AsyncMock()

    agent = AIAgent(
        transport=transport,
        tool_registry=registry,
        critic=critic,
        mission_id=mission_id,
        task_id=task_id,
    )

    tool_calls = [
        {
            "id": "call_001",
            "name": "exec_sandbox",
            "input": {"command": "rm -rf /tmp/test"},
        }
    ]
    emit = AsyncMock()

    # Patch no módulo onde is_irreversible é definido
    with patch("agent.critic.irreversible.is_irreversible", return_value=True):
        messages, summaries = await agent._execute_tools(tool_calls, emit)

    # Verifica que o Critic foi consultado
    critic.evaluate.assert_called_once()
    decision = critic.evaluate.call_args[0][0]
    assert decision.tool_name == "exec_sandbox"
    assert decision.mission_id == mission_id
    assert decision.task_id == task_id

    # Verifica que a tool foi bloqueada
    assert len(messages) == 1
    assert "BLOCKED_BY_CRITIC" in messages[0]["content"]
    assert summaries[0].succeeded is False

    # Verifica estado do agente
    assert agent._critic_blocked is True
    assert agent._critic_blocked_tool == "exec_sandbox"


@pytest.mark.asyncio
async def test_critic_evaluation_has_mission_and_task_id() -> None:
    """D.4: Decision criada pelo hook tem mission_id e task_id populados."""
    from agent.tools.registry import ToolRegistry

    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_make_reject_verdict())

    mission_id = uuid4()
    task_id = uuid4()

    registry = ToolRegistry()
    transport = MagicMock()

    agent = AIAgent(
        transport=transport,
        tool_registry=registry,
        critic=critic,
        mission_id=mission_id,
        task_id=task_id,
    )

    tool_calls = [{"id": "call_002", "name": "exec_sandbox", "input": {"cmd": "ls"}}]
    emit = AsyncMock()

    with patch("agent.critic.irreversible.is_irreversible", return_value=True):
        await agent._execute_tools(tool_calls, emit)

    decision = critic.evaluate.call_args[0][0]
    assert decision.mission_id == mission_id, (
        f"Decision.mission_id deve ser {mission_id}, mas é {decision.mission_id}"
    )
    assert decision.task_id == task_id, (
        f"Decision.task_id deve ser {task_id}, mas é {decision.task_id}"
    )
