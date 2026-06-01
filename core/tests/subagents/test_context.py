"""
Testa SubAgentContext — isolamento de contexto por construção.

A prova de isolamento é estrutural: verifica que build_subagent() instancia
AIAgent com memory_store=None, skill_manager=None e conversation_id novo.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

from agent.subagents.context import SubAgentContext
from agent.subagents.subagent import build_subagent


def test_context_system_prompt_contains_tools() -> None:
    ctx = SubAgentContext(
        task="pesquisar sobre Python",
        tools_allowed=["web_search", "read_file"],
    )
    prompt = ctx.build_system_prompt()
    assert "web_search" in prompt
    assert "read_file" in prompt


def test_context_system_prompt_contains_return_format() -> None:
    ctx = SubAgentContext(
        task="listar itens",
        tools_allowed=[],
        return_format="json_list",
    )
    prompt = ctx.build_system_prompt()
    assert "json_list" in prompt


def test_context_user_message_json() -> None:
    ctx = SubAgentContext(
        task="retorne dados",
        tools_allowed=[],
        return_format="json",
    )
    msg = ctx.build_user_message()
    assert "JSON" in msg


def test_context_extra_context_in_prompt() -> None:
    ctx = SubAgentContext(
        task="analisar",
        tools_allowed=[],
        extra_context="contexto secreto do pai",
    )
    prompt = ctx.build_system_prompt()
    assert "contexto secreto do pai" in prompt


def test_build_subagent_no_memory_store() -> None:
    """Subagente criado sem memory_store — isolamento garantido."""
    ctx = SubAgentContext(
        task="tarefa",
        tools_allowed=[],
    )
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    assert agent._memory_store is None


def test_build_subagent_no_skill_manager() -> None:
    """Subagente criado sem skill_manager."""
    ctx = SubAgentContext(task="tarefa", tools_allowed=[])
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    assert agent._skill_manager is None


def test_build_subagent_no_curator_compressor() -> None:
    """Subagente criado sem curator e sem compressor."""
    ctx = SubAgentContext(task="tarefa", tools_allowed=[])
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    assert agent._curator is None
    assert agent._compressor is None


def test_build_subagent_fresh_conversation_id() -> None:
    """Cada subagente recebe UUID novo (namespace separado do pai)."""
    ctx = SubAgentContext(task="tarefa", tools_allowed=[])
    mock_router = MagicMock()
    parent_conv_id = UUID("00000000-0000-0000-0000-000000000001")

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent1 = build_subagent(ctx, mock_router)
        agent2 = build_subagent(ctx, mock_router)

    assert agent1._conversation_id != parent_conv_id
    assert agent1._conversation_id != agent2._conversation_id


def test_build_subagent_restricted_tools() -> None:
    """Registry do filho contém apenas as tools permitidas."""
    ctx = SubAgentContext(
        task="tarefa",
        tools_allowed=["web_search"],
    )
    mock_router = MagicMock()

    with patch("agent.subagents.subagent.AnthropicTransport"):
        agent = build_subagent(ctx, mock_router)

    names = agent._registry.names()
    assert "web_search" in names
    # Tools não permitidas não devem estar no registry
    assert "shell" not in names
