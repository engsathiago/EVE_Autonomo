"""
A.3: Critic gate para skills irreversíveis — wire no AIAgent._execute_tools.

Casos cobertos:
1. Skill irreversible=True + Critic presente → evaluate() chamado, skill executa (approve)
2. Skill irreversible=True + Critic presente → evaluate() chamado, skill BLOQUEADA (reject)
3. Skill irreversible=False → Critic NÃO é invocado
4. Integration: critic_evaluations tem mission_id != NULL (requer Postgres — skip se ausente)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.core import AIAgent, ToolCallSummary
from agent.critic.critic import CriticVerdict, PersonaVerdict
from agent.tools.registry import ToolRegistry


def _approve_verdict() -> CriticVerdict:
    persona = PersonaVerdict(approve=True, confidence=0.9, reasoning="OK", concerns=[])
    return CriticVerdict(
        verdict="approve",
        mitigations=[],
        reasoning="Operação aprovada",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": "approve"},
    )


def _reject_verdict() -> CriticVerdict:
    persona = PersonaVerdict(
        approve=False,
        confidence=0.95,
        reasoning="Skill irreversível: pode apagar dados críticos",
        concerns=["dados permanentemente removidos"],
    )
    return CriticVerdict(
        verdict="reject",
        mitigations=[],
        reasoning="Critic rejeitou skill irreversível",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": "reject"},
    )


def _make_agent(
    critic: MagicMock | None = None,
    skill_manager: MagicMock | None = None,
    mission_id=None,
    task_id=None,
) -> AIAgent:
    transport = MagicMock()
    transport.chat = AsyncMock()
    return AIAgent(
        transport=transport,
        tool_registry=ToolRegistry(),
        critic=critic,
        skill_manager=skill_manager,
        mission_id=mission_id,
        task_id=task_id,
    )


def _make_skill_manager(skill_name: str, irreversible: bool) -> MagicMock:
    """Cria um SkillManager mock com um manifest parametrizado."""
    manifest = MagicMock()
    manifest.irreversible = irreversible

    skill_result = MagicMock()
    skill_result.output = {"result": "done"}

    manager = MagicMock()
    manager.get = MagicMock(return_value=manifest)
    manager.run = AsyncMock(return_value=skill_result)
    return manager


@pytest.mark.asyncio
async def test_critic_evaluates_irreversible_skill_and_proceeds() -> None:
    """Skill com irreversible=True dispara critic, veredito approve → skill executa."""
    mission_id = uuid4()
    task_id = uuid4()

    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_approve_verdict())

    skill_manager = _make_skill_manager("dangerous_skill", irreversible=True)
    agent = _make_agent(critic=critic, skill_manager=skill_manager, mission_id=mission_id, task_id=task_id)

    tool_calls = [{"id": "tc_001", "name": "skill__dangerous_skill", "input": {"param": "val"}}]
    emit = AsyncMock()

    messages, summaries = await agent._execute_tools(tool_calls, emit)

    # Critic foi consultado
    critic.evaluate.assert_called_once()
    decision = critic.evaluate.call_args[0][0]
    assert decision.tool_name == "dangerous_skill"
    assert decision.mission_id == mission_id
    assert decision.task_id == task_id

    # Skill executou — manager.run foi chamado
    skill_manager.run.assert_called_once()
    assert summaries[0].succeeded is True
    assert agent._critic_blocked is False


@pytest.mark.asyncio
async def test_critic_blocks_irreversible_skill() -> None:
    """Skill com irreversible=True, critic retorna reject → skill NÃO executa."""
    mission_id = uuid4()
    task_id = uuid4()

    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=_reject_verdict())

    skill_manager = _make_skill_manager("dangerous_skill", irreversible=True)
    agent = _make_agent(critic=critic, skill_manager=skill_manager, mission_id=mission_id, task_id=task_id)

    tool_calls = [{"id": "tc_002", "name": "skill__dangerous_skill", "input": {"param": "val"}}]
    emit = AsyncMock()

    messages, summaries = await agent._execute_tools(tool_calls, emit)

    # Critic foi consultado
    critic.evaluate.assert_called_once()

    # Skill NÃO executou
    skill_manager.run.assert_not_called()

    # Mensagem de bloqueio
    assert len(messages) == 1
    assert "BLOCKED_BY_CRITIC" in messages[0]["content"]
    assert "dangerous_skill" in messages[0]["content"]
    assert summaries[0].succeeded is False

    # Estado do agente
    assert agent._critic_blocked is True
    assert agent._critic_blocked_tool == "dangerous_skill"
    assert agent._critic_blocked_reason is not None


@pytest.mark.asyncio
async def test_critic_skips_safe_skill() -> None:
    """Skill com irreversible=False → Critic NÃO é invocado."""
    critic = MagicMock()
    critic.evaluate = AsyncMock()

    skill_manager = _make_skill_manager("safe_skill", irreversible=False)
    agent = _make_agent(critic=critic, skill_manager=skill_manager)

    tool_calls = [{"id": "tc_003", "name": "skill__safe_skill", "input": {}}]
    emit = AsyncMock()

    await agent._execute_tools(tool_calls, emit)

    # Critic NÃO foi consultado
    critic.evaluate.assert_not_called()
    skill_manager.run.assert_called_once()


# ---------------------------------------------------------------------------
# Integration: requer Postgres — skip se ausente
# ---------------------------------------------------------------------------

_PG_UP = bool(os.environ.get("POSTGRES_DSN") or os.environ.get("POSTGRES_URL"))


@pytest.mark.skipif(not _PG_UP, reason="postgres indisponível")
@pytest.mark.asyncio
async def test_critic_persists_mission_id() -> None:
    """Após avaliação de skill irreversível, critic_evaluations tem linha com mission_id != NULL."""
    import asyncpg

    from agent.critic.critic import Critic
    from agent.models.router import ModelRouter

    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("POSTGRES_URL", "")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)

    try:
        router = MagicMock(spec=ModelRouter)

        async def _fake_chat(**kwargs):  # type: ignore[no-untyped-def]
            return MagicMock(
                text='{"verdict":"approve","reasoning":"ok","mitigations":[]}',
                tool_calls=[],
                raw={},
                usage=MagicMock(input_tokens=10, output_tokens=10),
                model="mock:model",
                openrouter_cost_usd=None,
            )

        router.chat = AsyncMock(side_effect=_fake_chat)
        critic = Critic(model_router=router)

        mission_id = uuid4()
        task_id = uuid4()

        from agent.critic.critic import Decision

        decision = Decision(
            tool_name="dangerous_skill",
            tool_args={"x": 1},
            context_summary="Teste A.3",
            mission_id=mission_id,
            task_id=task_id,
        )

        await critic.evaluate(decision, db_pool=pool)

        row = await pool.fetchrow(
            "SELECT mission_id FROM critic_evaluations WHERE mission_id = $1 LIMIT 1",
            mission_id,
        )
        assert row is not None, "Linha com mission_id não encontrada em critic_evaluations"
    finally:
        await pool.close()
