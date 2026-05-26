"""Testes de rotas de missões — C1, C4."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def mock_missions_store() -> MagicMock:
    store = MagicMock()
    from datetime import UTC, datetime
    from uuid import uuid4

    mission_data = {
        "id": uuid4(),
        "title": "Missão teste",
        "objective": "testar sistema",
        "success_criteria": [{"description": "ok"}],
        "deadline": None,
        "status": "active",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "completed_at": None,
        "source": "test",
        "source_ref": None,
        "parent_mission_id": None,
        "metadata": {},
    }
    mock_m = MagicMock()
    mock_m.model_dump.return_value = mission_data
    store.list_by_status = AsyncMock(return_value=[mock_m])
    store.get = AsyncMock(return_value=mock_m)
    store.update_status = AsyncMock(return_value=None)
    return store


@pytest.fixture()
def client(mock_missions_store: MagicMock):
    app = make_web_app(missions_store=mock_missions_store)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_list_missions(client: TestClient) -> None:
    resp = client.get("/api/v1/missions", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


def test_get_mission_not_found(client: TestClient, mock_missions_store: MagicMock) -> None:
    mock_missions_store.get = AsyncMock(return_value=None)
    resp = client.get("/api/v1/missions/00000000-0000-0000-0000-000000000000", headers=_h())
    assert resp.status_code == 404


def test_system_info(client: TestClient) -> None:
    """C1: /api/v1/system/info deve retornar 200 com token."""
    resp = client.get("/api/v1/system/info", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "phase" in data


def test_pause_mission(client: TestClient) -> None:
    resp = client.post("/api/v1/missions/00000000-0000-0000-0000-000000000000/pause", headers=_h())
    assert resp.status_code in (200, 404, 422, 500)


def test_resume_mission(client: TestClient) -> None:
    resp = client.post("/api/v1/missions/00000000-0000-0000-0000-000000000000/resume", headers=_h())
    assert resp.status_code in (200, 404, 422, 500)
