"""Testes de rotas de subagentes — C4."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def client():
    app = make_web_app()
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_subagents_health(client: TestClient) -> None:
    resp = client.get("/api/v1/subagents", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "recent_runs" in data
