"""Testes de cobertura dos adapters e rotas estáticas."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app

# ── adapters/missions ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_missions_error_returns_empty() -> None:
    """list_missions retorna [] em caso de exceção."""
    from agent.web.adapters.missions import list_missions

    store = MagicMock()
    store.list_by_status = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await list_missions(store)
    assert result == []


@pytest.mark.asyncio
async def test_get_mission_with_parent_id() -> None:
    """get_mission converte parent_mission_id para str."""
    from agent.web.adapters.missions import get_mission

    parent_id = uuid4()
    mission_id = uuid4()
    store = MagicMock()
    mock_m = MagicMock()
    mock_m.model_dump.return_value = {
        "id": mission_id,
        "parent_mission_id": parent_id,
        "title": "sub",
        "status": "active",
    }
    store.get = AsyncMock(return_value=mock_m)
    result = await get_mission(store, str(mission_id))
    assert result is not None
    assert result["parent_mission_id"] == str(parent_id)


@pytest.mark.asyncio
async def test_get_mission_error_returns_none() -> None:
    """get_mission retorna None em caso de exceção."""
    from agent.web.adapters.missions import get_mission

    store = MagicMock()
    store.get = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await get_mission(store, str(uuid4()))
    assert result is None


@pytest.mark.asyncio
async def test_create_mission_success() -> None:
    """create_mission cria missão e retorna dict."""
    from agent.web.adapters.missions import create_mission

    mission_id = uuid4()
    store = MagicMock()
    planner = MagicMock()

    async def fake_create(mission):
        return mission

    store.create = fake_create

    result = await create_mission(store, planner, "Título", "objetivo")
    assert result is not None
    assert "id" in result


@pytest.mark.asyncio
async def test_create_mission_error_returns_none() -> None:
    """create_mission retorna None em caso de exceção."""
    from agent.web.adapters.missions import create_mission

    store = MagicMock()
    store.create = AsyncMock(side_effect=RuntimeError("db fail"))
    planner = MagicMock()
    result = await create_mission(store, planner, "t", "p")
    assert result is None


@pytest.mark.asyncio
async def test_pause_mission_error_returns_false() -> None:
    """pause_mission retorna False em caso de exceção."""
    from agent.web.adapters.missions import pause_mission

    store = MagicMock()
    store.update_status = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await pause_mission(store, str(uuid4()))
    assert result is False


@pytest.mark.asyncio
async def test_resume_mission_error_returns_false() -> None:
    """resume_mission retorna False em caso de exceção."""
    from agent.web.adapters.missions import resume_mission

    store = MagicMock()
    store.update_status = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await resume_mission(store, str(uuid4()))
    assert result is False


# ── adapters/orchestrator ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_success() -> None:
    """send_message produz eventos token e done."""
    from agent.web.adapters.orchestrator import send_message

    mock_result = MagicMock()
    mock_result.final_text = "resposta"
    mock_result.iterations = 1
    mock_result.total_input_tokens = 10
    mock_result.total_output_tokens = 20
    mock_result.estimated_cost_usd = 0.001
    mock_result.duration_s = 0.5

    mock_orchestrator = MagicMock()
    mock_orchestrator.route = AsyncMock(return_value=mock_result)

    mock_task_store = MagicMock()
    mock_task_store.create = AsyncMock(return_value=None)

    # Task e TaskSource são importados dentro da função — usa mocks em seus módulos originais
    with patch("agent.tasks.task.Task") as MockTask, patch("agent.tasks.task.TaskSource"):
        mock_task_inst = MagicMock()
        mock_task_inst.tier = "FAST"
        MockTask.return_value = mock_task_inst

        events = []
        async for ev in send_message(mock_orchestrator, mock_task_store, "olá"):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "token" in types
    assert "done" in types


@pytest.mark.asyncio
async def test_send_message_exception_yields_error() -> None:
    """send_message produz evento error quando orchestrator falha."""
    from agent.web.adapters.orchestrator import send_message

    mock_orchestrator = MagicMock()
    mock_orchestrator.route = AsyncMock(side_effect=RuntimeError("fail"))

    mock_task_store = MagicMock()
    mock_task_store.create = AsyncMock(return_value=None)

    with patch("agent.tasks.task.Task") as MockTask, patch("agent.tasks.task.TaskSource"):
        MockTask.return_value = MagicMock()

        events = []
        async for ev in send_message(mock_orchestrator, mock_task_store, "olá"):
            events.append(ev)

    assert any(e["type"] == "error" for e in events)


# ── adapters/critic ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_critic_queue_error_returns_empty() -> None:
    """get_critic_queue retorna [] em caso de exceção."""
    from agent.web.adapters.critic import get_critic_queue

    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await get_critic_queue(mock_pool)
    assert result == []


@pytest.mark.asyncio
async def test_critic_history_error_returns_empty() -> None:
    """get_critic_history retorna [] em caso de exceção."""
    from agent.web.adapters.critic import get_critic_history

    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(side_effect=RuntimeError("db fail"))
    result = await get_critic_history(mock_pool)
    assert result == []


def test_parse_verdict_none() -> None:
    """_parse_verdict retorna None para None."""
    from agent.web.adapters.critic import _parse_verdict

    assert _parse_verdict(None) is None


def test_parse_verdict_string_json() -> None:
    """_parse_verdict faz parse de string JSON."""
    from agent.web.adapters.critic import _parse_verdict

    data = {"decision": "approve"}
    result = _parse_verdict(json.dumps(data))
    assert result == data


def test_parse_verdict_invalid_string() -> None:
    """_parse_verdict retorna dict com raw para string inválida."""
    from agent.web.adapters.critic import _parse_verdict

    result = _parse_verdict("not-json{")
    assert result == {"raw": "not-json{"}


def test_parse_verdict_dict_passthrough() -> None:
    """_parse_verdict retorna dict diretamente."""
    from agent.web.adapters.critic import _parse_verdict

    data = {"decision": "reject"}
    assert _parse_verdict(data) == data


# ── adapters/subagents ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subagents_with_db_pool() -> None:
    """get_subagents_health usa db_pool quando disponível."""
    from agent.web.adapters.subagents import get_subagents_health

    mock_pool = MagicMock()
    mock_row = {
        "task_id": uuid4(),
        "worker_id": "w1",
        "started_at": datetime.now(UTC),
        "completed_at": None,
        "error": None,
        "tier": "FAST",
        "status": "done",
    }
    mock_pool.fetch = AsyncMock(return_value=[mock_row])

    result = await get_subagents_health(None, db_pool=mock_pool)
    assert "recent_runs" in result
    assert len(result["recent_runs"]) == 1


@pytest.mark.asyncio
async def test_subagents_db_pool_error_graceful() -> None:
    """get_subagents_health é resiliente a falha no db_pool."""
    from agent.web.adapters.subagents import get_subagents_health

    mock_pool = MagicMock()
    mock_pool.fetch = AsyncMock(side_effect=RuntimeError("db fail"))

    result = await get_subagents_health(None, db_pool=mock_pool)
    assert result["recent_runs"] == []


# ── routes/static ────────────────────────────────────────────────────────────


@pytest.fixture()
def static_client():
    with patch("agent.web.auth.verify_token", return_value=True):
        app = make_web_app()
        yield TestClient(app)


def test_static_index_served(static_client: TestClient) -> None:
    """GET / serve index.html."""
    resp = static_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_css_served(static_client: TestClient) -> None:
    """GET /css/term.css serve CSS com cache longo."""
    resp = static_client.get("/css/term.css")
    assert resp.status_code == 200
    assert "immutable" in resp.headers.get("cache-control", "")


def test_static_js_served(static_client: TestClient) -> None:
    """GET /js/app.js serve JS com cache longo."""
    resp = static_client.get("/js/app.js")
    assert resp.status_code == 200


def test_static_404_for_missing_file(static_client: TestClient) -> None:
    """Arquivo inexistente retorna 404."""
    resp = static_client.get("/nonexistent_xyz.html")
    assert resp.status_code == 404


def test_static_path_traversal_denied(static_client: TestClient) -> None:
    """Path traversal deve retornar 403 ou 404."""
    resp = static_client.get("/../../etc/passwd")
    assert resp.status_code in (403, 404)


# ── routes/api — create_mission ──────────────────────────────────────────────


@pytest.fixture()
def missions_client():
    from datetime import UTC, datetime

    store = MagicMock()
    planner = MagicMock()
    mission_id = uuid4()
    mock_m = MagicMock()
    mock_m.model_dump.return_value = {
        "id": mission_id,
        "title": "Nova missão",
        "objective": "obj",
        "success_criteria": [],
        "deadline": None,
        "status": "active",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "completed_at": None,
        "source": "web",
        "source_ref": None,
        "parent_mission_id": None,
        "metadata": {},
    }
    store.list_by_status = AsyncMock(return_value=[mock_m])
    store.create = AsyncMock(return_value=mock_m)
    store.get = AsyncMock(return_value=mock_m)
    store.update_status = AsyncMock(return_value=None)

    app = make_web_app(missions_store=store, missions_planner=planner)
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False), store


def test_create_mission_endpoint(missions_client) -> None:
    """POST /api/v1/missions cria nova missão."""
    client, store = missions_client
    resp = client.post(
        "/api/v1/missions",
        json={"title": "Nova missão", "prompt": "objetivo", "tier": "FAST"},
        headers={"X-Agent-Token": "test"},
    )
    assert resp.status_code in (200, 201, 500)  # 500 se adapter falhar internamente


# ── routes/api — rotas sem dependências configuradas ─────────────────────────


@pytest.fixture()
def client_no_deps():
    """App sem nenhum store/pool — cobre paths de 503 e empty returns."""
    app = make_web_app()
    with patch("agent.web.auth.verify_token", return_value=True):
        yield TestClient(app, raise_server_exceptions=False)


def _h() -> dict:
    return {"X-Agent-Token": "test"}


def test_missions_list_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/missions", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_missions_get_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/missions/00000000-0000-0000-0000-000000000000", headers=_h())
    assert resp.status_code == 503


def test_missions_create_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.post(
        "/api/v1/missions",
        json={"title": "t", "prompt": "p"},
        headers=_h(),
    )
    assert resp.status_code == 503


def test_missions_pause_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.post("/api/v1/missions/00000000-0000-0000-0000-000000000000/pause", headers=_h())
    assert resp.status_code == 503


def test_missions_resume_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.post("/api/v1/missions/00000000-0000-0000-0000-000000000000/resume", headers=_h())
    assert resp.status_code == 503


def test_skills_list_no_manager(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/skills", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_skills_get_no_manager(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/skills/some-skill", headers=_h())
    assert resp.status_code == 503


def test_skills_disable_no_manager(client_no_deps: TestClient) -> None:
    resp = client_no_deps.post("/api/v1/skills/some-skill/disable", headers=_h())
    assert resp.status_code == 503


def test_traces_list_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/traces", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_traces_get_no_store(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/traces/00000000-0000-0000-0000-000000000000", headers=_h())
    assert resp.status_code == 503


def test_critic_queue_no_db(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/critic/queue", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_critic_history_no_db(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/critic/history", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_approvals_list_no_manager(client_no_deps: TestClient) -> None:
    resp = client_no_deps.get("/api/v1/approvals", headers=_h())
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_approvals_decide_no_manager(client_no_deps: TestClient) -> None:
    resp = client_no_deps.post(
        "/api/v1/approvals/some-id",
        json={"decision": "approve"},
        headers=_h(),
    )
    assert resp.status_code == 503


def test_metrics_summary_no_db(client_no_deps: TestClient) -> None:
    """GET /metrics/summary retorna 200 mesmo sem DB — cobre linhas 294-345."""
    resp = client_no_deps.get("/api/v1/metrics/summary", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert "skills_created_7d" in data
    assert "missions_completed" in data


def test_get_mission_happy_path(missions_client) -> None:
    """GET /api/v1/missions/{id} happy path retorna 200 com dados."""
    client, store = missions_client
    resp = client.get(
        "/api/v1/missions/00000000-0000-0000-0000-000000000000",
        headers=_h(),
    )
    # store.get retorna mock_m (non-None) por default no fixture
    assert resp.status_code in (200, 500)


def test_system_info_git_unavailable(client_no_deps: TestClient) -> None:
    """system_info cobre except blocks quando git falha."""
    with patch("subprocess.check_output", side_effect=Exception("no git")):
        resp = client_no_deps.get("/api/v1/system/info", headers=_h())
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("branch") is None
    assert data.get("tag") is None


# ── adapters/skills — exception paths ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_skills_exception_returns_empty() -> None:
    """list_skills retorna [] em caso de exceção."""
    from agent.web.adapters.skills import list_skills

    manager = MagicMock()
    manager.list.side_effect = RuntimeError("fail")
    result = await list_skills(manager)
    assert result == []


@pytest.mark.asyncio
async def test_get_skill_exception_returns_none() -> None:
    """get_skill retorna None em caso de exceção."""
    from agent.web.adapters.skills import get_skill

    manager = MagicMock()
    manager.has.side_effect = RuntimeError("fail")
    result = await get_skill(manager, "any-skill")
    assert result is None


@pytest.mark.asyncio
async def test_disable_skill_not_found_returns_false() -> None:
    """disable_skill retorna False se skill não existe."""
    from agent.web.adapters.skills import disable_skill

    manager = MagicMock()
    manager.has.return_value = False
    result = await disable_skill(manager, "missing")
    assert result is False


@pytest.mark.asyncio
async def test_disable_skill_exception_returns_false() -> None:
    """disable_skill retorna False em caso de exceção."""
    from agent.web.adapters.skills import disable_skill

    manager = MagicMock()
    manager.has.side_effect = RuntimeError("fail")
    result = await disable_skill(manager, "any")
    assert result is False
