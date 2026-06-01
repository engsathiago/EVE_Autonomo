"""
Testes de integração para critic gating no AIAgent (D.4).

Usa mock do Critic para evitar LLM real; testa a lógica de gating
em _maybe_gate_tool sem dependências externas.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.critic.critic import CriticVerdict, PersonaVerdict


def _make_verdict(verdict: str) -> CriticVerdict:
    persona = PersonaVerdict(
        approve=(verdict == "approve"),
        confidence=0.9,
        reasoning="mock reasoning",
        concerns=[],
    )
    return CriticVerdict(
        verdict=verdict,
        mitigations=[],
        reasoning="mock reasoning",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": verdict},
    )


def _make_agent(critic_verdict: str):
    """Cria AIAgent mínimo com critic mockado."""

    from agent.core import AIAgent
    from agent.tools.registry import ToolRegistry
    from agent.transports.base import BaseTransport

    mock_critic = MagicMock()
    mock_critic.evaluate = AsyncMock(return_value=_make_verdict(critic_verdict))

    transport = MagicMock(spec=BaseTransport)
    registry = ToolRegistry()

    return AIAgent(
        transport=transport,
        tool_registry=registry,
        critic=mock_critic,
    )


@pytest.mark.asyncio
async def test_approve_tool_executes():
    """Critic APPROVE → tool deve executar normalmente (gate retorna None)."""
    agent = _make_agent("approve")
    result = await agent._maybe_gate_tool("send_telegram", {"chat_id": "1", "text": "hi"})
    assert result is None


@pytest.mark.asyncio
async def test_reject_tool_blocked():
    """Critic REJECT → gate retorna ToolResult com blocked_by_critic=True."""
    agent = _make_agent("reject")
    result = await agent._maybe_gate_tool("send_telegram", {"chat_id": "1", "text": "hi"})
    assert result is not None
    assert result.ok is False
    assert result.output.get("blocked_by_critic") is True
    assert "reject" in result.error


@pytest.mark.asyncio
async def test_escalate_tool_blocked():
    """Critic ESCALATE → gate retorna ToolResult com blocked_by_critic=True."""
    agent = _make_agent("escalate")
    result = await agent._maybe_gate_tool("fs_delete", {"path": "/important"})
    assert result is not None
    assert result.ok is False
    assert result.output.get("blocked_by_critic") is True


@pytest.mark.asyncio
async def test_timeout_treated_as_escalate():
    """Timeout de 30s → gate retorna bloqueio preventivo."""
    from agent.core import AIAgent
    from agent.tools.registry import ToolRegistry

    mock_critic = MagicMock()

    async def slow_evaluate(*args, **kwargs):
        await asyncio.sleep(9999)

    mock_critic.evaluate = slow_evaluate

    agent = AIAgent(
        transport=MagicMock(),
        tool_registry=ToolRegistry(),
        critic=mock_critic,
    )

    # Reduz timeout pra 0.05s no teste patchando wait_for
    original_wait = asyncio.wait_for

    async def fast_timeout(coro, timeout):
        raise TimeoutError

    import unittest.mock as mock_module
    with mock_module.patch("asyncio.wait_for", side_effect=fast_timeout):
        result = await agent._maybe_gate_tool("send_email", {"to": "x@y.com"})

    assert result is not None
    assert result.ok is False
    assert result.output.get("blocked_by_critic") is True


@pytest.mark.asyncio
async def test_safe_tool_no_gating():
    """Tools de leitura não passam pelo critic (gate retorna None diretamente)."""
    agent = _make_agent("reject")  # critic rejeita tudo — mas não deve ser chamado
    result = await agent._maybe_gate_tool("read_file", {"path": "/tmp/x.txt"})
    assert result is None
    # critic.evaluate não foi chamado
    agent._critic.evaluate.assert_not_awaited()
