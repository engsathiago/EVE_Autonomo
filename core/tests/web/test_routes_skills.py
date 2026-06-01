"""Testes de rotas de skills — C4."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def mock_skill_manager() -> MagicMock:
    manager = MagicMock()
    skill = MagicMock()
    skill.name = "test_skill"
    skill.description = "Skill de teste"
    skill.tags = ["test"]
    skill.version = "1.0"
    skill.steps = []
    manager.list.return_value = [skill]
    manager.has.return_value = True
    manager.get.return_value = skill
    return manager


@pytest.fixture()
def client(mock_skill_manager: MagicMock):
    app = make_web_app(skill_manager=mock_skill_manager)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_list_skills(client: TestClient) -> None:
    resp = client.get("/api/v1/skills", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "test_skill"


def test_get_skill(client: TestClient) -> None:
    resp = client.get("/api/v1/skills/test_skill", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test_skill"


def test_get_skill_not_found(client: TestClient, mock_skill_manager: MagicMock) -> None:
    mock_skill_manager.has.return_value = False
    resp = client.get("/api/v1/skills/unknown", headers=_h())
    assert resp.status_code == 404


def test_disable_skill(client: TestClient) -> None:
    resp = client.post("/api/v1/skills/test_skill/disable", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
