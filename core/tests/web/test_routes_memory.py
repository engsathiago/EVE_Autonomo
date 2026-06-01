"""Testes de rotas de memória — C4."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def mock_memory_store() -> MagicMock:
    store = MagicMock()
    from datetime import UTC, datetime
    from uuid import uuid4

    entry = MagicMock()
    entry.id = uuid4()
    entry.content = "Conteúdo de memória de teste"
    entry.kind.value = "episodic"
    entry.created_at = datetime.now(UTC)
    entry.tags = []

    store.search_hybrid = AsyncMock(return_value=[(entry, 0.87)])
    return store


@pytest.fixture()
def client(mock_memory_store: MagicMock):
    app = make_web_app(memory_store=mock_memory_store)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_memory_search(client: TestClient) -> None:
    resp = client.post("/api/v1/memory/search", headers=_h(), json={"query": "teste"})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["similarity"] == 0.87


def test_memory_search_no_store() -> None:
    app = make_web_app(memory_store=None)
    with patch("agent.web.auth.verify_token", return_value=True):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/memory/search",
            headers={"X-Agent-Token": "test"},
            json={"query": "x"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
