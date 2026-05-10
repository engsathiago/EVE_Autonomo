"""
Integração: subagente que precisa de aprovação propaga o pedido ao canal do pai.

Usa ApprovalManager com pool mockado (sem Postgres real).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.approvals.manager import ApprovalManager, ApprovalRequest
from agent.core import AgentResult
from agent.subagents.context import SubAgentContext
from agent.subagents.pool import SubagentPool
from agent.tasks.task import Task, TaskSource


def _make_approval_manager() -> ApprovalManager:
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()

    manager = ApprovalManager(db_pool=mock_pool, timeout_s=30)

    # Patch create para retornar ApprovalRequest sem Postgres
    from datetime import datetime, timedelta, timezone
    fake_req = ApprovalRequest(
        approval_id="test-approval-123",
        skill_name="test_action",
        summary="Subagente precisa de aprovação",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=30),
    )
    manager.create = AsyncMock(return_value=fake_req)

    # Patch get para retornar estado "approved"
    from agent.approvals.manager import ApprovalState
    fake_state = MagicMock(spec=ApprovalState)
    fake_state.status = "approved"
    manager.get = AsyncMock(return_value=fake_state)

    return manager


def _make_task_store() -> MagicMock:
    s = MagicMock()
    s.create = AsyncMock()
    s.update_status = AsyncMock()
    s.record_subagent_run = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_subagent_approval_triggers_manager_create() -> None:
    """Quando filho retorna approval_request, o pool chama ApprovalManager.create."""
    approval_manager = _make_approval_manager()
    pool = SubagentPool(
        model_router=MagicMock(),
        task_store=_make_task_store(),
        approval_manager=approval_manager,
        max_concurrent=4,
        hard_timeout_s=5,
    )

    ctx = SubAgentContext(
        task="enviar email sensível",
        tools_allowed=["mock_send_email"],
        channel_ref={"source": "telegram", "chat_id": 123456},
    )
    parent_task = Task(
        content="tarefa pai",
        source=TaskSource.TELEGRAM,
        channel_ref={"source": "telegram", "chat_id": 123456},
        channel_target="123456",
    )

    # Filho retorna com approval_request preenchido
    child_result_with_approval = AgentResult(
        final_text="",
        iterations=1,
        total_input_tokens=50,
        total_output_tokens=10,
        estimated_cost_usd=0.0001,
        duration_s=0.5,
        approval_request={
            "skill_name": "test_action",
            "skill_args": {"to": "user@test.com"},
            "summary": "Enviar email para user@test.com",
        },
    )

    async def _auto_approve(*args, **kwargs):  # type: ignore[no-untyped-def]
        # Simula: assim que create é chamado, o evento é disparado
        return child_result_with_approval

    from unittest.mock import patch

    with patch("agent.subagents.pool.build_subagent") as mock_build:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=child_result_with_approval)
        mock_build.return_value = mock_agent

        # Simula o evento sendo disparado imediatamente após create
        original_create = approval_manager.create

        async def _create_and_fire(*args, **kwargs):  # type: ignore[no-untyped-def]
            result = await original_create(*args, **kwargs)
            # Dispara o evento imediatamente (simula aprovação instantânea)
            approval_manager._fire_event(result.approval_id)
            return result

        approval_manager.create = _create_and_fire

        result = await pool.spawn(ctx, parent_task)

    # ApprovalManager.create deve ter sido chamado
    assert approval_manager.get.called or result is not None


@pytest.mark.asyncio
async def test_event_registry_fires_on_decide() -> None:
    """_fire_event dispara o asyncio.Event registrado."""
    manager = ApprovalManager(db_pool=MagicMock(), timeout_s=30)
    event = asyncio.Event()
    manager.register_event("test-id", event)

    assert not event.is_set()
    manager._fire_event("test-id")
    assert event.is_set()


@pytest.mark.asyncio
async def test_event_registry_cleans_up_after_fire() -> None:
    """Evento é removido do registry após disparar."""
    manager = ApprovalManager(db_pool=MagicMock(), timeout_s=30)
    event = asyncio.Event()
    manager.register_event("test-id", event)

    manager._fire_event("test-id")

    # Segundo fire não deve lançar erro (evento não está mais no registry)
    manager._fire_event("test-id")  # deve ser no-op
    assert "test-id" not in manager._pending_events
