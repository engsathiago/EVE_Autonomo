"""Testa AutonomousLoop — sem chamar LLM diretamente."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.autonomous.loop import (
    MAX_STEPS_PER_TICK,
    AutonomousLoop,
    LoopReport,
)
from agent.missions.store import MissionStep


def _make_mission(mission_id=None, status="active"):
    m = MagicMock()
    m.id = mission_id or uuid4()
    m.title = "Missão teste"
    m.status = status
    m.updated_at = datetime.now(tz=timezone.utc)
    return m


def _make_step(seq=0, status="pending", retry_count=0):
    s = MagicMock(spec=MissionStep)
    s.id = uuid4()
    s.sequence = seq
    s.description = f"Step {seq}"
    s.status = status
    s.retry_count = retry_count
    return s


def _make_loop(pending_steps=None, active_missions=None):
    mission_store = MagicMock()
    orchestrator = MagicMock()
    task_store = MagicMock()

    missions = active_missions or [_make_mission()]
    steps = pending_steps if pending_steps is not None else [_make_step()]

    mission_store.list_active = AsyncMock(return_value=missions)
    mission_store.get_pending_steps = AsyncMock(return_value=steps)
    mission_store.get_all_steps = AsyncMock(return_value=steps)
    mission_store.update_step = AsyncMock()
    mission_store.update_status = AsyncMock()
    mission_store.add_step = AsyncMock(return_value=_make_step())

    task_store.create = AsyncMock()

    result = MagicMock()
    result.final_text = "resultado"
    orchestrator.route = AsyncMock(return_value=result)

    return AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
    )


@pytest.mark.asyncio
async def test_loop_does_not_call_llm_directly() -> None:
    """Loop não chama LLM — apenas despacha para Orchestrator."""
    loop = _make_loop()

    # Mock de 'embed' e qualquer LLM — se chamar, falha
    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    assert report.steps_dispatched >= 1
    # Garante que orchestrator.route foi chamado (despacho), não LLM direto
    loop._orchestrator.route.assert_called()


@pytest.mark.asyncio
async def test_loop_respects_max_steps_per_tick() -> None:
    """Loop não dispara mais que MAX_STEPS_PER_TICK steps em um tick."""
    # 10 steps pendentes para 1 missão
    many_steps = [_make_step(seq=i) for i in range(10)]
    loop = _make_loop(pending_steps=many_steps)

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    assert report.steps_dispatched <= MAX_STEPS_PER_TICK


@pytest.mark.asyncio
async def test_loop_triggers_replan_after_retry_limit() -> None:
    """Step com retry_count >= STEP_FAILURE_RETRY_LIMIT deve disparar replan."""
    from agent.autonomous.loop import STEP_FAILURE_RETRY_LIMIT

    exhausted_step = _make_step(seq=0, retry_count=STEP_FAILURE_RETRY_LIMIT)
    loop = _make_loop(pending_steps=[exhausted_step])

    planner = MagicMock()
    new_plan = MagicMock()
    new_plan.steps = ["Step alternativo"]
    planner.replan = AsyncMock(return_value=new_plan)
    loop._planner = planner

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    planner.replan.assert_called_once()
    assert report.replans_triggered == 1


@pytest.mark.asyncio
async def test_loop_completes_mission_when_all_steps_done() -> None:
    """Quando todos os steps estão done, missão é marcada como done."""
    done_step = _make_step(seq=0, status="done")
    mission = _make_mission()
    loop = _make_loop(pending_steps=[], active_missions=[mission])

    # get_pending_steps → vazio; get_all_steps → done
    loop._mission_store.get_pending_steps = AsyncMock(return_value=[])
    loop._mission_store.get_all_steps = AsyncMock(return_value=[done_step])

    with patch("agent.autonomous.loop.needs_critic", return_value=False):
        report = await loop.tick()

    loop._mission_store.update_status.assert_called_with(mission.id, "done")
    assert report.missions_completed == 1
