"""Testa as personas do Critic e regras de síntese."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.critic.critic import Critic, Decision
from agent.orchestrator.tiers import ExecutionTier


def _make_router(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    router = MagicMock()
    router.chat = AsyncMock(return_value=response)
    return router


def _persona_json(approve: bool, confidence: float = 0.8, concerns: list | None = None) -> str:
    return json.dumps(
        {
            "approve": approve,
            "confidence": confidence,
            "reasoning": "razão de teste",
            "concerns": concerns or [],
        }
    )


@pytest.fixture
def decision() -> Decision:
    return Decision(
        tool_name="fs_delete",
        tool_args={"path": "/workspace/dados.csv"},
        context_summary="Agente quer deletar arquivo temporário",
        tier=ExecutionTier.FAST,
    )


@pytest.mark.asyncio
async def test_technical_reviewer_flags_invalid_args(decision: Decision) -> None:
    """Técnico com confidence baixa retorna approve=False."""
    low_confidence = json.dumps(
        {
            "approve": False,
            "confidence": 0.2,
            "reasoning": "path parece ser de produção, não temporário",
            "concerns": ["arquivo pode ser necessário", "sem backup visível"],
        }
    )
    synth_json = json.dumps(
        {
            "verdict": "reject",
            "mitigations": [],
            "reasoning": "ambos rejeitam",
            "escalation_message": "",
        }
    )

    router = _make_router(low_confidence)

    critic = Critic(router)
    technical = await critic._run_technical(decision)

    assert technical.approve is False
    assert len(technical.concerns) >= 1


@pytest.mark.asyncio
async def test_devils_advocate_default_rejects(decision: Decision) -> None:
    """Advogado do diabo sem objeções respondidas → approve=False por default."""
    rejects_json = json.dumps(
        {
            "approve": False,
            "confidence": 0.9,
            "reasoning": "arquivo pode ser necessário; sem rollback",
            "concerns": [
                "e se o arquivo for lido por outro processo?",
                "há backup desta informação?",
                "existe versão reversível desta ação?",
            ],
        }
    )
    router = _make_router(rejects_json)
    router.chat = AsyncMock(return_value=MagicMock(text=rejects_json))

    critic = Critic(router)
    devils = await critic._run_devils_advocate(decision)

    assert devils.approve is False
    assert len(devils.concerns) >= 3


@pytest.mark.asyncio
async def test_synthesizer_never_invents_middle_ground(decision: Decision) -> None:
    """
    Quando ambos rejeitam, sintetizador deve retornar 'reject' — não inventa
    meio-termo que ignora concerns.
    """
    both_reject = _persona_json(False, 0.9)
    synth_response = json.dumps(
        {
            "verdict": "reject",
            "mitigations": [],
            "reasoning": "Ambos rejeitam com alta confiança. Ação não deve ser executada.",
            "escalation_message": "",
        }
    )

    call_count = {"n": 0}

    async def chat_side(**kw):
        call_count["n"] += 1
        resp = MagicMock()
        if call_count["n"] <= 2:
            resp.text = both_reject
        else:
            resp.text = synth_response
        return resp

    router = MagicMock()
    router.chat = AsyncMock(side_effect=chat_side)

    critic = Critic(router)
    verdict = await critic.evaluate(decision)

    assert verdict.verdict == "reject"
    # Verifica que sintetizador recebeu os pareceres — chamou chat 3 vezes
    assert call_count["n"] == 3
