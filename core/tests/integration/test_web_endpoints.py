"""Smoke dos endpoints da Web UI (F11).

Usa ASGITransport do httpx para testar sem servidor real.
Requer Postgres em localhost:5432 (ou POSTGRES_HOST env var).
"""

from __future__ import annotations

import os

import asyncpg
import httpx
import pytest
import pytest_asyncio

_PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
_PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
_PG_USER = os.getenv("POSTGRES_USER", "agent")
_PG_PASS = os.getenv("POSTGRES_PASSWORD", "qualquercoisa123")
_PG_DB = os.getenv("POSTGRES_DB", "agent")
_TEST_TOKEN = "test-token-f11"


@pytest_asyncio.fixture
async def db_pool():
    try:
        pool = await asyncpg.create_pool(
            host=_PG_HOST,
            port=_PG_PORT,
            user=_PG_USER,
            password=_PG_PASS,
            database=_PG_DB,
            min_size=1,
            max_size=2,
            command_timeout=5,
        )
        yield pool
        await pool.close()
    except Exception:
        pytest.skip("Postgres indisponível")


@pytest_asyncio.fixture
async def client(db_pool):
    from agent.missions.store import MissionStore
    from agent.tasks.store import TaskStore
    from agent.web.auth import write_token
    from agent.web.routes.api import configure
    from agent.web.server import make_web_app

    write_token(_TEST_TOKEN)
    app = make_web_app()

    @app.on_event("startup")
    async def _setup():
        configure(
            db_pool=db_pool,
            missions_store=MissionStore(db_pool),
            task_store=TaskStore(db_pool),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_static_index(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_missions_endpoint(client):
    r = await client.get("/api/v1/missions", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_skills_endpoint(client):
    r = await client.get("/api/v1/skills", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_critic_queue_endpoint(client):
    r = await client.get("/api/v1/critic/queue", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_critic_history_endpoint(client):
    r = await client.get("/api/v1/critic/history", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_subagents_endpoint(client):
    r = await client.get("/api/v1/subagents", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "active" in body
    assert "recent_runs" in body


@pytest.mark.asyncio
async def test_approvals_endpoint(client):
    r = await client.get("/api/v1/approvals", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_metrics_summary_endpoint(client):
    r = await client.get("/api/v1/metrics/summary", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "skills_created_7d" in body
    assert "missions_completed" in body


@pytest.mark.asyncio
async def test_traces_endpoint(client):
    r = await client.get("/api/v1/traces", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


@pytest.mark.asyncio
async def test_system_info_endpoint(client):
    r = await client.get("/api/v1/system/info", headers={"X-Agent-Token": _TEST_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "version" in body


@pytest.mark.asyncio
async def test_auth_required(client):
    r = await client.get("/api/v1/missions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_rejected(client):
    r = await client.get("/api/v1/missions", headers={"X-Agent-Token": "invalid-token"})
    assert r.status_code == 401
