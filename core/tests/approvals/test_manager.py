"""Testes do ApprovalManager (sem Postgres real — usa mocks asyncpg)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.approvals.manager import (
    AlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalManager,
    ApprovalNotFoundError,
    ApprovalRequest,
)


def _make_pool(fetchrow_return=None, fetch_return=None, execute_return="UPDATE 1"):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock(return_value=execute_return)

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=None),
        )
    )
    return pool, conn


@pytest.mark.asyncio
async def test_create_returns_approval_request():
    pool, conn = _make_pool()
    manager = ApprovalManager(pool, timeout_s=1800)

    result = await manager.create(
        session_id="tg:123",
        skill_name="mock_send_email",
        skill_args={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
        summary="Enviar email",
        channel="telegram",
    )

    assert isinstance(result, ApprovalRequest)
    assert result.skill_name == "mock_send_email"
    assert result.type == "approval_request"
    assert result.expires_at > datetime.now(tz=UTC)
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_expires_at_respects_timeout():
    pool, conn = _make_pool()
    manager = ApprovalManager(pool, timeout_s=60)

    before = datetime.now(tz=UTC)
    result = await manager.create(
        session_id="cli",
        skill_name="x",
        skill_args={},
        summary="test",
        channel="cli",
    )
    after = datetime.now(tz=UTC)

    assert result.expires_at >= before + timedelta(seconds=59)
    assert result.expires_at <= after + timedelta(seconds=61)


@pytest.mark.asyncio
async def test_get_not_found():
    pool, conn = _make_pool(fetchrow_return=None)
    manager = ApprovalManager(pool)

    with pytest.raises(ApprovalNotFoundError):
        await manager.get("nonexistent-id")


@pytest.mark.asyncio
async def test_decide_approve_updates_status():
    now = datetime.now(tz=UTC)
    row = {
        "id": "abc",
        "session_id": "tg:1",
        "skill_name": "x",
        "skill_args": {},
        "summary": "s",
        "channel": "telegram",
        "channel_ref": {},
        "status": "pending",
        "decided_by": None,
        "decided_at": None,
        "expires_at": now + timedelta(hours=1),
        "created_at": now,
    }
    updated_row = {**row, "status": "approved", "decided_by": "user42", "decided_at": now}

    pool, conn = _make_pool(fetchrow_return=row)
    # Second fetchrow (after UPDATE RETURNING) returns updated_row
    conn.fetchrow = AsyncMock(side_effect=[row, updated_row])

    manager = ApprovalManager(pool)
    state = await manager.decide("abc", "approve", "user42")

    assert state.status == "approved"
    assert state.decided_by == "user42"


@pytest.mark.asyncio
async def test_decide_is_idempotent():
    now = datetime.now(tz=UTC)
    row = {
        "id": "abc",
        "session_id": "tg:1",
        "skill_name": "x",
        "skill_args": {},
        "summary": "s",
        "channel": "telegram",
        "channel_ref": {},
        "status": "approved",
        "decided_by": "user1",
        "decided_at": now,
        "expires_at": now + timedelta(hours=1),
        "created_at": now,
    }
    pool, conn = _make_pool(fetchrow_return=row)
    manager = ApprovalManager(pool)

    with pytest.raises(AlreadyDecidedError) as exc_info:
        await manager.decide("abc", "approve", "user2")

    assert exc_info.value.state.status == "approved"


@pytest.mark.asyncio
async def test_decide_expired_approval():
    now = datetime.now(tz=UTC)
    row = {
        "id": "abc",
        "session_id": "tg:1",
        "skill_name": "x",
        "skill_args": {},
        "summary": "s",
        "channel": "telegram",
        "channel_ref": {},
        "status": "pending",
        "decided_by": None,
        "decided_at": None,
        "expires_at": now - timedelta(minutes=1),
        "created_at": now - timedelta(hours=1),
    }
    pool, conn = _make_pool(fetchrow_return=row)
    manager = ApprovalManager(pool)

    with pytest.raises(ApprovalExpiredError):
        await manager.decide("abc", "approve", "user1")

    # Should have updated status to expired
    conn.execute.assert_called_once()
