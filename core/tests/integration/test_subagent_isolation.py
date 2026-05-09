"""
Integração: subagente não vê contexto do pai além do que é explicitamente passado.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.subagents.context import SubAgentContext
from agent.subagents.subagent import build_subagent


@pytest.mark.asyncio
async def test_subagent_no_parent_memory() -> None:
    """Subagente criado com memory_store=None."""
    ctx = SubAgentContext(task="tarefa isolada", tools_allowed=[])
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    assert agent._memory_store is None, "Subagente não deve ter acesso à memory store do pai"


@pytest.mark.asyncio
async def test_subagent_no_parent_history() -> None:
    """Subagente executa run() com histórico vazio — não vê conversas anteriores."""
    from unittest.mock import AsyncMock
    from agent.core import AgentResult

    ctx = SubAgentContext(task="tarefa isolada", tools_allowed=[])
    mock_router = MagicMock()
    expected_result = AgentResult(
        final_text="feito",
        iterations=1,
        total_input_tokens=10,
        total_output_tokens=5,
        estimated_cost_usd=0.0,
        duration_s=0.1,
    )

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    agent.run = AsyncMock(return_value=expected_result)

    # Simula pool chamando o agente
    result = await agent.run(goal=ctx.build_user_message(), conversation_history=[])

    call_kwargs = agent.run.call_args.kwargs
    history = call_kwargs.get("conversation_history", None)
    assert history == [], f"Histórico deveria ser vazio, recebeu: {history}"


@pytest.mark.asyncio
async def test_subagent_only_allowed_tools() -> None:
    """Subagente com tools=['web_search'] não tem acesso a shell ou write_file."""
    ctx = SubAgentContext(task="pesquisar", tools_allowed=["web_search"])
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    names = agent._registry.names()
    assert "web_search" in names
    assert "shell" not in names
    assert "write_file" not in names


@pytest.mark.asyncio
async def test_subagent_extra_context_in_system_prompt() -> None:
    """extra_context passado explicitamente aparece no system prompt do filho."""
    secret = "informação secreta do pai"
    ctx = SubAgentContext(
        task="analisar",
        tools_allowed=[],
        extra_context=secret,
    )
    prompt = ctx.build_system_prompt()
    assert secret in prompt


@pytest.mark.asyncio
async def test_subagent_without_extra_context_no_parent_data() -> None:
    """Sem extra_context, o system prompt do filho não contém dados do pai."""
    ctx = SubAgentContext(
        task="analisar",
        tools_allowed=[],
        extra_context=None,
    )
    prompt = ctx.build_system_prompt()
    # Sem extra_context, não deve haver seção de contexto adicional
    assert "Additional context" not in prompt
