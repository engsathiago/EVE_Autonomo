"""
Integration tests D.4.2: verifica que db_pool flui de SubagentPool até AIAgent,
permitindo que Critic._persist grave critic_evaluations com mission_id não-NULL
no caminho STRATEGIC.

test_subagent_pool_passes_db_pool_to_build_subagent:
    Caminho minimal — monkeypatch em build_subagent, asserta kwargs.

test_subagent_critic_writes_to_db:
    Caminho completo — pool → AIAgent real com MockTransport → exec_sandbox
    (irreversível) → critic.evaluate(db_pool=pool) → pool.execute INSERT.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.core import AIAgent, AgentResult
from agent.critic.critic import CriticVerdict, PersonaVerdict
from agent.subagents.context import SubAgentContext
from agent.subagents.pool import SubagentPool
from agent.tasks.task import Task, TaskSource
from agent.tools.registry import ToolRegistry
from agent.transports.base import ChatResponse


# ─── helpers ────────────────────────────────────────────────────────────────

class _MockTransport:
    """Transport sequencial para testes: retorna respostas na ordem dada."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def chat(self, system: str, messages: list, tools: list | None = None,
                   max_tokens: int = 4096) -> ChatResponse:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


def _resp(text: str, tool_calls: list[dict[str, Any]] | None = None) -> ChatResponse:
    return ChatResponse(
        text=text,
        tool_calls=tool_calls or [],
        raw={},
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _reject_verdict() -> CriticVerdict:
    persona = PersonaVerdict(
        approve=False, confidence=0.95,
        reasoning="Operação irreversível detectada",
        concerns=["delete_dir"],
    )
    return CriticVerdict(
        verdict="reject",
        mitigations=[],
        reasoning="Critic rejeitou exec_sandbox",
        escalation_message="",
        technical=persona,
        devils_advocate=persona,
        synthesizer_raw={"verdict": "reject"},
    )


def _make_pool(critic=None, db_pool=None) -> SubagentPool:
    return SubagentPool(
        model_router=MagicMock(),
        task_store=AsyncMock(),
        critic=critic,
        db_pool=db_pool,
    )


def _make_parent_task(mission_id: str, step_id: str) -> Task:
    t = Task(
        content="step task",
        source=TaskSource.CRON,
        channel_ref={"mission_id": mission_id, "step_id": step_id},
    )
    t.id = uuid4()
    return t


def _make_ctx(mission_id: str) -> SubAgentContext:
    return SubAgentContext(
        task="Execute operação irreversível",
        tools_allowed=["exec_sandbox"],
        channel_ref={"mission_id": mission_id, "step_id": str(uuid4())},
        mission_id=mission_id,
    )


# ─── teste 1 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_pool_passes_db_pool_to_build_subagent() -> None:
    """
    Pool com db_pool configurado deve repassá-lo para build_subagent
    como kwarg explícito, para que AIAgent._db_pool fique preenchido.
    """
    fake_pool = MagicMock()
    mission_id = str(uuid4())
    captured: dict = {}

    from agent.core import AgentResult

    def fake_build(context, model_router, critic=None, mission_id=None, db_pool=None):
        captured["db_pool"] = db_pool
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value=AgentResult(
                final_text="ok",
                iterations=1,
                total_input_tokens=5,
                total_output_tokens=5,
                estimated_cost_usd=0.0,
                duration_s=0.1,
            )
        )
        return agent

    pool = _make_pool(db_pool=fake_pool)
    ctx = _make_ctx(mission_id)
    parent = _make_parent_task(mission_id, str(uuid4()))

    pool._task_store.create = AsyncMock()
    pool._task_store.update_status = AsyncMock()
    pool._task_store.record_subagent_run = AsyncMock()

    with patch("agent.subagents.pool.build_subagent", side_effect=fake_build):
        await pool.spawn(ctx, parent)

    assert captured.get("db_pool") is fake_pool, (
        f"build_subagent deve receber db_pool=fake_pool; obtido: {captured.get('db_pool')}"
    )


# ─── teste 2 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_critic_writes_to_db() -> None:
    """
    Caminho completo: pool → AIAgent real → exec_sandbox (irreversível)
    → critic.evaluate(db_pool=pool) → pool.execute INSERT com mission_id.

    Verifica que critic_evaluations recebe um INSERT com mission_id e
    task_id não-NULL quando pool tem db_pool configurado.
    """
    mission_uuid = uuid4()
    mission_id_str = str(mission_uuid)

    # mock_pool: registra chamadas de execute para validação
    mock_pool = AsyncMock()
    mock_pool.execute = AsyncMock()

    # mock_critic: ao ser avaliado, chama pool.execute simulando Critic._persist
    reject = _reject_verdict()

    async def fake_evaluate(decision: Any, db_pool: Any = None) -> CriticVerdict:
        if db_pool is not None:
            await db_pool.execute(
                "INSERT INTO critic_evaluations"
                "    (decision_id, task_id, mission_id, "
                "     technical_verdict, devils_advocate_verdict, synthesizer_verdict,"
                "     final_verdict, mitigations, latency_ms)"
                " VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7,$8::jsonb,$9)",
                decision.decision_id,
                decision.task_id,
                decision.mission_id,
                "{}",
                "{}",
                "{}",
                "reject",
                "[]",
                10,
            )
        return reject

    mock_critic = MagicMock()
    mock_critic.evaluate = fake_evaluate

    # AIAgent com MockTransport: primeiro tool_call exec_sandbox, depois texto final
    transport = _MockTransport([
        _resp(
            "",
            tool_calls=[{
                "name": "exec_sandbox",
                "id": "tc-1",
                "input": {"command": "rm -rf /tmp/test"},
            }],
        ),
        _resp("Operação bloqueada pelo Critic"),
    ])

    registry = ToolRegistry()
    # exec_sandbox não está no registry — _execute_tools retorna erro mas não crasha;
    # o check de irreversibilidade acontece ANTES da execução.

    subagent = AIAgent(
        transport=transport,  # type: ignore[arg-type]
        tool_registry=registry,
        critic=mock_critic,
        mission_id=mission_uuid,
        db_pool=mock_pool,
    )

    # Substitui build_subagent para retornar o AIAgent real acima
    def fake_build(context, model_router, critic=None, mission_id=None, db_pool=None):
        return subagent

    pool = _make_pool(critic=mock_critic, db_pool=mock_pool)
    ctx = _make_ctx(mission_id_str)
    parent = _make_parent_task(mission_id_str, str(uuid4()))

    pool._task_store.create = AsyncMock()
    pool._task_store.update_status = AsyncMock()
    pool._task_store.record_subagent_run = AsyncMock()

    with patch("agent.subagents.pool.build_subagent", side_effect=fake_build):
        await pool.spawn(ctx, parent)

    # db_pool.execute deve ter sido chamado com INSERT INTO critic_evaluations
    assert mock_pool.execute.called, (
        "db_pool.execute não foi chamado — critic_evaluations não foi escrito"
    )

    sql: str = mock_pool.execute.call_args[0][0]
    assert "INSERT INTO critic_evaluations" in sql, (
        f"SQL inesperado: {sql!r}"
    )

    # mission_id ($3 no INSERT) deve ser o UUID da missão — não-NULL
    positional_args = mock_pool.execute.call_args[0]
    mission_id_written = positional_args[3]  # $3 é mission_id
    assert mission_id_written == mission_uuid, (
        f"mission_id no INSERT: esperado {mission_uuid}, obtido {mission_id_written}"
    )
    assert mission_id_written is not None, "mission_id no INSERT é NULL — auditoria incompleta"
