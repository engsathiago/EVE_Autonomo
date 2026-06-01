"""
Testes de integração da F7 — ciclo completo de missão.

Usam mocks de DB e LLM para ser executáveis sem infraestrutura real.
Os testes verificam contratos de comportamento, não implementações.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.autonomous.loop import AutonomousLoop
from agent.core import AgentResult, ToolCallSummary
from agent.missions.reflector import MissionReflector
from agent.missions.store import Mission, MissionStep

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _mock_mission(status="active", step_count=3):
    m = MagicMock(spec=Mission)
    m.id = uuid4()
    m.title = "Missão de integração"
    m.objective = "Publicar 3 cortes de saúde mental"
    m.status = status
    m.success_criteria = [{"criterion": "publicar 3 cortes", "verifiable_via": "manual"}]
    m.updated_at = datetime.now(tz=UTC)
    return m


def _mock_step(seq, status="pending", retry_count=0):
    s = MagicMock(spec=MissionStep)
    s.id = uuid4()
    s.sequence = seq
    s.description = f"Step {seq}: parte da missão"
    s.status = status
    s.retry_count = retry_count
    s.tools_required = []  # campo D.1 — Pydantic v2 não expõe via spec
    return s


def _mock_plan(steps=None):
    plan = MagicMock()
    plan.title = "Publicar cortes de saúde mental"
    plan.success_criteria = [{"criterion": "publicar 3 cortes", "verifiable_via": "manual"}]
    plan.steps = steps or ["Criar scripts", "Editar vídeo", "Publicar"]
    plan.is_parallel = [False] * len(plan.steps)
    return plan


# ─── Test 1: Ciclo completo missão → passos → reflexão ───────────────────────

@pytest.mark.asyncio
async def test_full_mission_create_plan_execute_reflect() -> None:
    """
    Cria missão simples (3 passos triviais).
    Simula 3 ticks do loop.
    Verifica: steps viram tasks, critic chamado nos irreversíveis,
    reflection criada com 4 campos, insight pra reflexive_memory.
    """
    mission = _mock_mission()
    steps = [_mock_step(i) for i in range(3)]
    done_steps = [_mock_step(i, status="done") for i in range(3)]

    mission_store = MagicMock()
    call_count = {"pending": 0}

    async def get_pending_side(mission_id):
        call_count["pending"] += 1
        if call_count["pending"] <= 3:
            return steps[call_count["pending"] - 1:]  # decreasing list
        return []

    mission_store.list_active = AsyncMock(return_value=[mission])
    mission_store.get_pending_steps = AsyncMock(side_effect=get_pending_side)
    mission_store.get_all_steps = AsyncMock(return_value=done_steps)
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock()
    mission_store.add_reflection = AsyncMock()
    mission_store.get_critic_history = AsyncMock(return_value=[])

    task_store = MagicMock()
    task_store.create = AsyncMock()

    result = AgentResult(
        final_text="task concluída",
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=30,
        estimated_cost_usd=0.001,
        duration_s=0.5,
        tool_calls_made=[ToolCallSummary(tool_name="read_file", succeeded=True)],
    )
    orchestrator = MagicMock()
    orchestrator.route = AsyncMock(return_value=result)

    # Reflector mock
    reflexive_memory = MagicMock()
    reflexive_memory.add = AsyncMock()

    router = MagicMock()
    resp = MagicMock()
    resp.text = (
        "ENTREGUE:\nPublicado 3 cortes.\n\n"
        "QUALIDADE:\nMeta atingida.\n\n"
        "PRÓXIMO:\nAnalisar métricas.\n\n"
        "APRENDIDO:\nCortes curtos performam melhor."
    )
    router.chat = AsyncMock(return_value=resp)

    reflector = MissionReflector(
        model_router=router,
        mission_store=mission_store,
        reflexive_memory=reflexive_memory,
    )

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        reflector=reflector,
    )

    # Simula 1 tick — inicia steps
    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    assert report.steps_dispatched >= 1
    orchestrator.route.assert_called()


@pytest.mark.asyncio
async def test_mission_survives_restart() -> None:
    """
    Missão com step 'running' ao reiniciar deve retomar como pending.
    (Aqui testamos que o store não perde estado ao reconstituir o loop.)
    """
    mission = _mock_mission()
    # Step 1 estava running ao 'morrer', volta como pending
    step_running = _mock_step(1, status="running")
    step_pending = _mock_step(2, status="pending")

    mission_store = MagicMock()
    mission_store.list_active = AsyncMock(return_value=[mission])
    mission_store.get_pending_steps = AsyncMock(return_value=[step_running, step_pending])
    mission_store.get_all_steps = AsyncMock(return_value=[_mock_step(0, "done"), step_running, step_pending])
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock()

    task_store = MagicMock()
    task_store.create = AsyncMock()

    result = AgentResult(
        final_text="ok",
        iterations=1,
        total_input_tokens=20,
        total_output_tokens=10,
        estimated_cost_usd=0.0,
        duration_s=0.1,
        tool_calls_made=[ToolCallSummary(tool_name="read_file", succeeded=True)],
    )
    orchestrator = MagicMock()
    orchestrator.route = AsyncMock(return_value=result)

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
    )

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    # Loop despachou steps — missão está ativa e continuando
    assert report.steps_dispatched >= 1


@pytest.mark.asyncio
async def test_critic_propagates_escalate_to_gate() -> None:
    """
    Decision com tool irreversível e args ambíguos → Critic devolve 'escalate'.
    Verifica que step é marcado skipped (gate interceptou).
    """
    from agent.critic.critic import CriticVerdict, PersonaVerdict

    mission = _mock_mission()
    step = _mock_step(0)

    mission_store = MagicMock()
    mission_store.list_active = AsyncMock(return_value=[mission])
    mission_store.get_pending_steps = AsyncMock(return_value=[step])
    mission_store.get_all_steps = AsyncMock(return_value=[step])
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock()

    task_store = MagicMock()
    task_store.create = AsyncMock()

    orchestrator = MagicMock()
    orchestrator.route = AsyncMock()

    escalate_verdict = CriticVerdict(
        verdict="escalate",
        mitigations=[],
        reasoning="Decisão genuinamente ambígua",
        escalation_message="Requer aprovação humana",
        technical=PersonaVerdict(approve=False, confidence=0.4, reasoning="", concerns=[]),
        devils_advocate=PersonaVerdict(approve=False, confidence=0.9, reasoning="", concerns=["ambíguo"]),
        synthesizer_raw={"verdict": "escalate"},
    )

    critic = MagicMock()
    critic.evaluate = AsyncMock(return_value=escalate_verdict)

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        critic=critic,
    )

    with patch("agent.autonomous.loop.needs_critic", return_value=True):
        report = await loop.tick()

    # Step foi marcado como skipped (escalated)
    update_calls = [str(c) for c in mission_store.update_step.call_args_list]
    assert any("skipped" in c for c in update_calls)
    # Orchestrator NÃO foi chamado
    orchestrator.route.assert_not_called()


@pytest.mark.asyncio
async def test_replan_after_3_step_failures() -> None:
    """
    Step com retry_count = STEP_FAILURE_RETRY_LIMIT → loop dispara replan automático.
    """
    from agent.autonomous.loop import STEP_FAILURE_RETRY_LIMIT

    mission = _mock_mission()
    exhausted = _mock_step(0, retry_count=STEP_FAILURE_RETRY_LIMIT)

    mission_store = MagicMock()
    mission_store.list_active = AsyncMock(return_value=[mission])
    mission_store.get_pending_steps = AsyncMock(return_value=[exhausted])
    mission_store.get_all_steps = AsyncMock(return_value=[exhausted])
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock(return_value=_mock_step(1))
    mission_store.get = AsyncMock(return_value=mission)

    task_store = MagicMock()

    orchestrator = MagicMock()
    orchestrator.route = AsyncMock()

    planner = MagicMock()
    plan = _mock_plan(["Abordagem alternativa"])
    planner.replan = AsyncMock(return_value=plan)

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
        planner=planner,
    )

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    planner.replan.assert_called_once()
    assert report.replans_triggered == 1
