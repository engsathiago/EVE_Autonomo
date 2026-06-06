"""Regressão D.4: critic_evaluations criadas no mission flow não devem ser órfãs."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AIAgent
from agent.critic.critic import CriticVerdict, Decision, PersonaVerdict


def _make_verdict(verdict: str = "reject") -> CriticVerdict:
    persona = PersonaVerdict(approve=(verdict != "reject"), confidence=0.9, reasoning="test", concerns=[])
    return CriticVerdict(
        verdict=verdict,
        mitigations=[],
        reasoning=f"Critic decidiu: {verdict}",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": verdict},
    )


@pytest.mark.asyncio
async def test_critic_evaluations_not_orphaned_in_mission_flow() -> None:
    """
    D.4 (C6): quando Critic avalia tool de step de missão, Decision tem
    mission_id != NULL e task_id != NULL — sem critic_evaluations órfãs.
    """
    from agent.tools.registry import ToolRegistry

    mission_id = uuid4()
    task_id = uuid4()

    received_decisions: list[Decision] = []

    async def _capture_evaluate(decision: Decision, *, db_pool=None) -> CriticVerdict:
        received_decisions.append(decision)
        return _make_verdict("reject")

    critic = MagicMock()
    critic.evaluate = AsyncMock(side_effect=_capture_evaluate)

    registry = ToolRegistry()
    transport = MagicMock()

    agent = AIAgent(
        transport=transport,
        tool_registry=registry,
        critic=critic,
        mission_id=mission_id,
        task_id=task_id,
    )

    tool_calls = [
        {"id": "c1", "name": "exec_sandbox", "input": {"cmd": "rm /tmp/x"}},
        {"id": "c2", "name": "fs_delete", "input": {"path": "/tmp/y"}},
        {"id": "c3", "name": "web_search", "input": {"query": "ai news"}},
    ]
    emit = AsyncMock()

    # Patch no módulo onde is_irreversible é definido, não em agent.core
    with patch("agent.critic.irreversible.is_irreversible") as mock_irrev:
        mock_irrev.side_effect = lambda name: name in ("exec_sandbox", "fs_delete")
        with patch.object(registry, "execute", new_callable=AsyncMock) as mock_exec:
            from agent.tools.base import ToolResult
            mock_exec.return_value = ToolResult(ok=True, output={"result": "ok"})
            await agent._execute_tools(tool_calls, emit)

    # Deve ter avaliado exatamente 2 tools (as irreversíveis)
    assert len(received_decisions) == 2, (
        f"Esperado 2 avaliações, recebeu {len(received_decisions)}"
    )

    # TODAS as Decisions devem ter mission_id e task_id populados (C6)
    for d in received_decisions:
        assert d.mission_id is not None, (
            f"Decision para '{d.tool_name}' tem mission_id=NULL — seria órfã!"
        )
        assert d.task_id is not None, (
            f"Decision para '{d.tool_name}' tem task_id=NULL — seria órfã!"
        )
        assert d.mission_id == mission_id
        assert d.task_id == task_id
