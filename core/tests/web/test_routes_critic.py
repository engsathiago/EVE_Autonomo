"""Testes de rotas do Crítico — C4."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def mock_db_pool() -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=[])
    return pool


@pytest.fixture()
def client(mock_db_pool: MagicMock):
    app = make_web_app(db_pool=mock_db_pool)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_critic_queue(client: TestClient) -> None:
    resp = client.get("/api/v1/critic/queue", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_critic_history(client: TestClient) -> None:
    resp = client.get("/api/v1/critic/history", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []
