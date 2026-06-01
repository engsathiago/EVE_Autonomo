"""Testa MissionPlanner — rejeição de objetivos subjetivos e steps paralelos."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.missions.planner import MissionPlan, MissionPlanner, ObjectiveSubjectiveError


def _make_router(response_text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = response_text
    router = MagicMock()
    router.chat = AsyncMock(return_value=resp)
    return router


_VALID_PLAN = json.dumps(
    {
        "title": "Canal de cortes de saúde mental",
        "success_criteria": [
            {"criterion": "publicar 10 cortes em 30 dias", "verifiable_via": "manual"},
            {"criterion": "atingir 500 visualizações por corte", "verifiable_via": "metric"},
        ],
        "steps": [
            "Definir calendário editorial com 10 temas de saúde mental",
            "Gravar e editar 5 cortes na primeira semana",
            "[PARALELO 1]: Publicar no Instagram os primeiros 5 cortes",
            "[PARALELO 1]: Publicar no TikTok os primeiros 5 cortes",
            "Analisar métricas e ajustar estratégia",
        ],
    }
)

_SUBJECTIVE_RESPONSE = json.dumps(
    {
        "error": "objetivo_subjetivo",
        "reason": "Não é possível definir critério verificável para 'fazer um bom canal'",
    }
)


@pytest.fixture
def planner() -> MissionPlanner:
    return MissionPlanner(_make_router(_VALID_PLAN))


@pytest.mark.asyncio
async def test_planner_rejects_subjective_objective() -> None:
    """Planner deve lançar ObjectiveSubjectiveError para objetivos vagos."""
    router = _make_router(_SUBJECTIVE_RESPONSE)
    planner = MissionPlanner(router)

    with pytest.raises(ObjectiveSubjectiveError):
        await planner.plan("fazer um bom canal")


@pytest.mark.asyncio
async def test_planner_marks_parallel_steps(planner: MissionPlanner) -> None:
    """Steps com prefixo [PARALELO N]: devem ter is_parallel=True."""
    plan = await planner.plan("lança canal de cortes de saúde mental até 30/jun")

    assert isinstance(plan, MissionPlan)
    assert len(plan.steps) == 5

    # Steps 2 e 3 (índice 2 e 3) têm prefixo [PARALELO 1]
    assert plan.is_parallel[2] is True
    assert plan.is_parallel[3] is True

    # Steps sem prefixo não são paralelos
    assert plan.is_parallel[0] is False
    assert plan.is_parallel[1] is False


@pytest.mark.asyncio
async def test_replan_preserves_success_criteria() -> None:
    """replan() deve manter success_criteria original da missão."""
    original_criteria = [{"criterion": "publicar 10 cortes", "verifiable_via": "manual"}]

    # Mock mission_store
    mission_store = MagicMock()
    mission = MagicMock()
    mission.title = "Canal de cortes"
    mission.objective = "lança canal"
    mission.success_criteria = original_criteria

    step1 = MagicMock()
    step1.description = "Definir calendário"
    step1.status = "done"

    step2 = MagicMock()
    step2.description = "Gravar 5 cortes"
    step2.status = "failed"

    mission_store.get = AsyncMock(return_value=mission)
    mission_store.get_all_steps = AsyncMock(return_value=[step1, step2])

    replan_response = json.dumps(
        {
            "steps": [
                "Regravar cortes com nova abordagem",
                "Publicar na semana seguinte",
            ]
        }
    )
    router = _make_router(replan_response)
    planner = MissionPlanner(router)

    mission_id = uuid4()
    plan = await planner.replan(
        mission_id,
        reason="Cortes falharam no primeiro take",
        mission_store=mission_store,
    )

    assert plan.success_criteria == original_criteria
    assert len(plan.steps) == 2
