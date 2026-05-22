"""
Factory que instancia um AIAgent filho com contexto isolado.

Garantias de isolamento (por construção, não por convenção):
- memory_store=None   → filho não vê memórias do pai
- curator=None        → sem curadoria de memória
- compressor=None     → sem compressão de histórico
- conversation_id=novo UUID → namespace separado
- tool_registry com subset restrito
- skill_manager=None  → sem match semântico automático de skills
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from agent.config import get_settings
from agent.core import AIAgent
from agent.subagents.context import SubAgentContext
from agent.tools.registry import ToolRegistry, register_builtin
from agent.transports.anthropic import AnthropicTransport

if TYPE_CHECKING:
    from agent.models.router import ModelRouter


def build_subagent(
    context: SubAgentContext,
    model_router: ModelRouter,
) -> AIAgent:
    settings = get_settings()

    registry = _build_restricted_registry(context.tools_allowed)

    # Fallback inerte: AIAgent prefere model_router quando presente (core.py:_chat).
    # Este transport só é usado se model_router=None — não é o caminho ativo em produção.
    transport = AnthropicTransport(model=settings.anthropic.planner_model)

    from agent.config import AgentSettings

    # default_model armazenado para informação; roteamento real vai por model_router.
    child_settings = AgentSettings(
        name="subagent",
        default_model=settings.anthropic.planner_model,
        max_iterations=context.max_iterations,
        reflection_every=999,  # desabilita reflection no filho
    )

    return AIAgent(
        transport=transport,
        tool_registry=registry,
        reflector_transport=None,  # sem reflection
        settings=child_settings,
        memory_store=None,  # isolamento: filho não vê memória do pai
        curator=None,
        compressor=None,
        conversation_id=uuid4(),  # namespace separado
        skill_manager=None,  # sem auto-matching de skills
        model_router=model_router,
    )


def _build_restricted_registry(tools_allowed: list[str]) -> ToolRegistry:
    """Cria registry somente com as tools autorizadas para este subagente."""
    full_registry = ToolRegistry()
    register_builtin(full_registry)

    restricted = ToolRegistry()
    for name in tools_allowed:
        tool = full_registry.get(name)
        if tool is not None:
            restricted.register(tool)

    return restricted
