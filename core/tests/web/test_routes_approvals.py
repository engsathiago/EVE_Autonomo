"""Testes de rotas de aprovações — C4 e C6.

C6: Aprovação via UI dispara mesmo handler do Telegram.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def mock_approval_manager() -> MagicMock:
    manager = MagicMock()
    from datetime import UTC, datetime

    ap = MagicMock()
    ap.id = "ap-001"
    ap.tool_name = "send_email"
    ap.tool_args = {"to": "user@example.com"}
    ap.context = "Enviar relatório semanal"
    ap.channel_ref = {"chat_id": "123"}
    ap.created_at = datetime.now(UTC)
    ap.expires_at = None

    manager.list_pending = AsyncMock(return_value=[ap])
    manager.decide = AsyncMock()
    return manager


@pytest.fixture()
def client(mock_approval_manager: MagicMock):
    app = make_web_app(approval_manager=mock_approval_manager)
    # Patcha verify_token para sempre retornar True nestes testes
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test-token"}


def test_list_approvals(client: TestClient) -> None:
    resp = client.get("/api/v1/approvals", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["tool_name"] == "send_email"


def test_approve_calls_same_handler(
    client: TestClient,
    mock_approval_manager: MagicMock,
) -> None:
    """C6: decide() do ApprovalManager deve ser chamado com decision='approve'."""
    resp = client.post(
        "/api/v1/approvals/ap-001",
        headers=_h(),
        json={"decision": "approve"},
    )
    assert resp.status_code == 200
    mock_approval_manager.decide.assert_called_once_with(
        "ap-001", decision="approve", decided_by="web"
    )


def test_reject_calls_same_handler(
    client: TestClient,
    mock_approval_manager: MagicMock,
) -> None:
    """C6: decide() deve ser chamado com decision='reject'."""
    resp = client.post(
        "/api/v1/approvals/ap-001",
        headers=_h(),
        json={"decision": "reject", "note": "Não autorizado"},
    )
    assert resp.status_code == 200
    mock_approval_manager.decide.assert_called_once_with(
        "ap-001", decision="reject", decided_by="web:Não autorizado"
    )


def test_invalid_decision_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/approvals/ap-001",
        headers=_h(),
        json={"decision": "maybe"},
    )
    assert resp.status_code == 400
