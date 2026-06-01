"""Testes dos endpoints de approval (sem banco real)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.approvals import make_approvals_router_full
from agent.approvals.manager import (
    AlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalState,
)


def _make_state(status="pending", **kwargs) -> ApprovalState:
    now = datetime.now(tz=UTC)
    return ApprovalState(
        id="test-approval-id",
        session_id="tg:123",
        skill_name="mock_send_email",
        skill_args={"to": "a@b.com"},
        summary="Enviar email",
        channel="telegram",
        channel_ref={},
        status=status,
        decided_by=None,
        decided_at=None,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        **kwargs,
    )


def _make_app(manager_mock, skill_manager_mock=None):
    app = FastAPI()
    router = make_approvals_router_full(
        get_approval_manager=lambda: manager_mock,
        get_skill_manager=lambda: skill_manager_mock,
    )
    app.include_router(router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_get_approval_found():
    manager = MagicMock()
    manager.get = AsyncMock(return_value=_make_state())
    client = _make_app(manager)

    resp = client.get("/v1/approvals/test-approval-id")
    assert resp.status_code == 200
    assert resp.json()["id"] == "test-approval-id"


@pytest.mark.asyncio
async def test_get_approval_not_found():
    manager = MagicMock()
    manager.get = AsyncMock(side_effect=ApprovalNotFoundError("x"))
    client = _make_app(manager)

    resp = client.get("/v1/approvals/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_returns_rejected():
    now = datetime.now(tz=UTC)
    state = ApprovalState(
        id="test-approval-id",
        session_id="tg:123",
        skill_name="mock_send_email",
        skill_args={},
        summary="s",
        channel="telegram",
        channel_ref={},
        status="rejected",
        decided_by="user1",
        decided_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
    )
    manager = MagicMock()
    manager.decide = AsyncMock(return_value=state)
    client = _make_app(manager)

    resp = client.post("/v1/approvals/test-approval-id", json={"decision": "reject", "decided_by": "user1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_approve_expired_returns_409():
    manager = MagicMock()
    manager.decide = AsyncMock(side_effect=ApprovalExpiredError("x"))
    client = _make_app(manager)

    resp = client.post("/v1/approvals/test-approval-id", json={"decision": "approve", "decided_by": "user1"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_decide_idempotent_returns_current_status():
    existing = _make_state(status="approved")
    manager = MagicMock()
    manager.decide = AsyncMock(side_effect=AlreadyDecidedError(existing))
    client = _make_app(manager)

    resp = client.post("/v1/approvals/test-approval-id", json={"decision": "approve", "decided_by": "user1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_list_pending():
    manager = MagicMock()
    manager.list_pending = AsyncMock(return_value=[_make_state()])
    client = _make_app(manager)

    resp = client.get("/v1/approvals")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
