"""C.3 — Validação runtime Fase 7 (Missões + Crítico Autônomo).

Valida:
  1. missions + mission_steps: MissionStore.create() + add_step() persist em Postgres.
  2. critic_evaluations: Critic.evaluate() com ModelRouter stubado persiste em Postgres.

LLM não é chamado — ModelRouter.chat() é substituído por mock que retorna JSON pré-definido.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest

pytestmark = pytest.mark.runtime

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_REPO / "core" / "src"))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    yield pool
    await pool.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_response(text: str):
    """Cria objeto que imita ChatResponse com .text."""
    resp = MagicMock()
    resp.text = text
    return resp


def _make_mock_router(
    technical_json: dict,
    devils_json: dict,
    synthesizer_json: dict,
) -> MagicMock:
    """Cria ModelRouter mock que retorna respostas pré-definidas sem LLM real."""
    call_count = 0
    responses = [
        json.dumps(technical_json),
        json.dumps(devils_json),
        json.dumps(synthesizer_json),
    ]

    async def _chat(**kwargs) -> MagicMock:
        nonlocal call_count
        text = responses[call_count % len(responses)]
        call_count += 1
        return _make_chat_response(text)

    router = MagicMock()
    router.chat = _chat
    return router


# ---------------------------------------------------------------------------
# Teste 1: missions + mission_steps
# ---------------------------------------------------------------------------


async def test_mission_create_and_step_persist_to_postgres(pg_pool, tmp_path):
    """MissionStore.create() + add_step() persistem em missions + mission_steps."""
    from agent.missions.store import MissionStore

    store = MissionStore(pool=pg_pool)

    mission = await store.create(
        title="rt-test-c3 mission",
        objective="Validar persistência de missão em runtime",
        success_criteria=[{"criterion": "Missão criada no banco", "measurable": True}],
        deadline=None,
        source="runtime-test",
        source_ref="test_phase_f7_real",
    )

    mission_id = mission.id
    assert str(mission_id)  # UUID válido

    row = await pg_pool.fetchrow("SELECT * FROM missions WHERE id = $1", mission_id)
    assert row is not None
    assert row["title"] == "rt-test-c3 mission"
    assert row["status"] == "active"

    # Adiciona step
    step = await store.add_step(
        mission_id,
        description="Passo de runtime test C.3",
        sequence=0,
    )

    step_row = await pg_pool.fetchrow(
        "SELECT * FROM mission_steps WHERE id = $1", step.id
    )
    assert step_row is not None
    assert step_row["mission_id"] == mission_id
    assert step_row["status"] == "pending"

    # Evidência
    dest = Path(__file__).parent / "f7_mission_id.txt"
    dest.write_text(str(mission_id))
    print(f"\n[C.3] missions INSERT OK → mission_id={mission_id}")
    print(f"[C.3] mission_steps INSERT OK → step_id={step.id}")


async def test_mission_status_update(pg_pool):
    """MissionStore.update_status() atualiza status em Postgres."""
    from agent.missions.store import MissionStore

    store = MissionStore(pool=pg_pool)

    mission = await store.create(
        title="rt-test-c3 status update",
        objective="Testar transição de status",
        success_criteria=[{"criterion": "Status atualizado", "measurable": True}],
        deadline=None,
        source="runtime-test",
        source_ref=None,
    )

    await store.update_status(mission.id, "done")

    row = await pg_pool.fetchrow("SELECT status FROM missions WHERE id = $1", mission.id)
    assert row["status"] == "done"
    print(f"\n[C.3] mission status → done OK (id={mission.id})")


# ---------------------------------------------------------------------------
# Teste 2: critic_evaluations
# ---------------------------------------------------------------------------


async def test_critic_evaluate_with_stub_persists_to_postgres(pg_pool, tmp_path):
    """Critic.evaluate() com ModelRouter stub persiste em critic_evaluations."""
    from agent.critic.critic import Critic, Decision

    technical_response = {
        "approve": True,
        "confidence": 0.9,
        "reasoning": "Tecnicamente sólido — teste de runtime",
        "concerns": [],
    }
    devils_response = {
        "approve": True,
        "confidence": 0.75,
        "reasoning": "Sem objeções críticas — teste controlado",
        "concerns": ["Risco teórico mínimo"],
    }
    synthesizer_response = {
        "verdict": "approve",
        "mitigations": [],
        "reasoning": "Ambas personas aprovam — approve definitivo",
        "escalation_message": "",
    }

    mock_router = _make_mock_router(technical_response, devils_response, synthesizer_response)

    critic = Critic(model_router=mock_router)

    # Cria missão real para satisfazer FK de critic_evaluations.mission_id
    from agent.missions.store import MissionStore
    store = MissionStore(pool=pg_pool)
    mission = await store.create(
        title="rt-test-c3 critic parent mission",
        objective="Missão pai para teste de critic_evaluations",
        success_criteria=[{"criterion": "Auxiliar critic test", "measurable": True}],
        deadline=None,
        source="runtime-test",
        source_ref=None,
    )

    decision = Decision(
        tool_name="list_files",
        tool_args={"path": "/tmp/runtime-test"},
        context_summary="Teste de runtime C.3 — valida persistência de critic_evaluations",
        affects_external_world=False,
        is_first_of_its_kind=True,
        mission_id=mission.id,
    )

    # Precisa de missão existente para FK (ou sem mission_id)
    decision_id = decision.decision_id

    verdict = await critic.evaluate(decision, db_pool=pg_pool)

    assert verdict.verdict in ("approve", "approve_with_mitigation", "reject", "escalate")

    row = await pg_pool.fetchrow(
        "SELECT * FROM critic_evaluations WHERE decision_id = $1", decision_id
    )
    assert row is not None, f"critic_evaluations não tem linha para decision_id={decision_id}"
    assert row["final_verdict"] == verdict.verdict

    eval_id = row["id"]

    # Evidência
    dest = Path(__file__).parent / "f7_critic_eval_id.txt"
    dest.write_text(str(eval_id))
    print(f"\n[C.3] critic_evaluations INSERT OK → eval_id={eval_id}, verdict={verdict.verdict}")
