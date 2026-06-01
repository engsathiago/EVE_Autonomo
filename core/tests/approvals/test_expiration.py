"""Testes do ApprovalScheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.approvals.manager import ApprovalManager
from agent.approvals.scheduler import ApprovalScheduler


@pytest.mark.asyncio
async def test_scheduler_calls_expire_stale():
    manager = MagicMock(spec=ApprovalManager)
    manager.expire_stale = AsyncMock(return_value=2)

    scheduler = ApprovalScheduler(manager, interval_s=0)
    scheduler.start()

    # Dá tempo para o loop disparar pelo menos uma vez
    await asyncio.sleep(0.05)
    await scheduler.stop()

    manager.expire_stale.assert_called()


@pytest.mark.asyncio
async def test_scheduler_stop_cancels_task():
    manager = MagicMock(spec=ApprovalManager)
    manager.expire_stale = AsyncMock(return_value=0)

    scheduler = ApprovalScheduler(manager, interval_s=9999)
    scheduler.start()
    assert scheduler._task is not None
    assert not scheduler._task.done()

    await scheduler.stop()
    assert scheduler._task.done()


@pytest.mark.asyncio
async def test_scheduler_handles_exception_gracefully():
    manager = MagicMock(spec=ApprovalManager)
    manager.expire_stale = AsyncMock(side_effect=RuntimeError("db down"))

    scheduler = ApprovalScheduler(manager, interval_s=0)
    scheduler.start()

    # Mesmo com erro, o scheduler não deve crashar o processo
    await asyncio.sleep(0.05)
    await scheduler.stop()

    # expire_stale foi chamado mas exceção não propagou
    manager.expire_stale.assert_called()
