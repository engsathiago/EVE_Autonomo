"""Testes de rotas de traces — C4."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


def _make_task(status_val="done"):
    from datetime import UTC, datetime

    from agent.tasks.task import TaskSource, TaskStatus

    t = MagicMock()
    t.id = uuid4()
    t.content = "tarefa de teste"
    t.status = TaskStatus(status_val)
    t.tier = "FAST"
    t.source = TaskSource.API
    t.created_at = datetime.now(UTC)
    t.started_at = None
    t.completed_at = None
    t.error = None
    t.parent_id = None
    t.channel_ref = {}
    return t


@pytest.fixture()
def mock_task_store() -> MagicMock:
    store = MagicMock()
    task = _make_task()
    store.list_by_status = AsyncMock(return_value=[task])
    store.get = AsyncMock(return_value=task)
    store.get_tree = AsyncMock(return_value=[])
    return store


@pytest.fixture()
def client(mock_task_store: MagicMock):
    app = make_web_app(task_store=mock_task_store)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_list_traces(client: TestClient) -> None:
    resp = client.get("/api/v1/traces", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


def test_get_trace(client: TestClient, mock_task_store: MagicMock) -> None:
    tid = str(uuid4())
    mock_task_store.get = AsyncMock(return_value=_make_task())
    resp = client.get(f"/api/v1/traces/{tid}", headers=_h())
    assert resp.status_code == 200
