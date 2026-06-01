"""Testes dos health endpoints (F10)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.deploy.health import (
    _check_scheduler,
    _check_subagent_pool,
    make_health_router,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def app_with_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "agent.db"
    sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
    monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

    app = FastAPI()
    app.include_router(make_health_router())
    return TestClient(app, raise_server_exceptions=False)


# ── /health/live ───────────────────────────────────────────────────────────────

class TestLiveness:
    def test_returns_200(self, app_with_health: TestClient) -> None:
        resp = app_with_health.get("/health/live")
        assert resp.status_code == 200

    def test_response_body(self, app_with_health: TestClient) -> None:
        resp = app_with_health.get("/health/live")
        assert resp.json()["status"] == "alive"

    def test_fast_response(self, app_with_health: TestClient) -> None:
        """C4: Liveness não deve fazer I/O pesado — <50ms."""
        import time
        # Aquecer
        app_with_health.get("/health/live")
        times_ms = []
        for _ in range(3):
            t0 = time.monotonic()
            app_with_health.get("/health/live")
            times_ms.append((time.monotonic() - t0) * 1000)
        median = sorted(times_ms)[1]
        assert median < 50, f"liveness mediana {median:.1f}ms, esperado <50ms"

    def test_no_db_access_in_liveness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """C4: liveness não abre banco — funciona mesmo sem SQLite válido."""
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/path/db.db")
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/live")
        assert resp.status_code == 200


# ── /health/ready ─────────────────────────────────────────────────────────────

class TestReadiness:
    def test_returns_200_when_sqlite_ok(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "ok.db"
        conn = sqlite3.connect(str(db))
        conn.execute("SELECT 1")
        conn.close()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    def test_returns_503_when_sqlite_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/path/agent.db")
        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 503

    def test_checks_dict_in_response(self, app_with_health: TestClient) -> None:
        resp = app_with_health.get("/health/ready")
        body = resp.json()
        assert "checks" in body
        assert "sqlite" in body["checks"]


# ── _check_scheduler ──────────────────────────────────────────────────────────

class TestCheckScheduler:
    def test_skipped_when_none(self) -> None:
        result = _check_scheduler(None)
        assert result["ok"] is True
        assert result.get("skipped") is True

    def test_ok_when_running(self) -> None:
        mock = MagicMock()
        mock.scheduler.running = True
        result = _check_scheduler(mock)
        assert result["ok"] is True

    def test_not_ok_when_stopped(self) -> None:
        mock = MagicMock()
        mock.scheduler.running = False
        result = _check_scheduler(mock)
        assert result["ok"] is False


# ── _check_subagent_pool ──────────────────────────────────────────────────────

class TestCheckSubagentPool:
    def test_skipped_when_none(self) -> None:
        result = _check_subagent_pool(None)
        assert result["ok"] is True
        assert result.get("skipped") is True

    def test_ok_when_has_capacity(self) -> None:
        mock = MagicMock()
        mock._semaphore._value = 5
        result = _check_subagent_pool(mock)
        assert result["ok"] is True

    def test_not_ok_when_no_capacity(self) -> None:
        mock = MagicMock()
        mock._semaphore._value = 0
        result = _check_subagent_pool(mock)
        assert result["ok"] is False


# ── /health/deep ─────────────────────────────────────────────────────────────

class TestDeepHealth:
    def test_structure_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "deep.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 50}),
        ):
            resp = client.get("/health/deep")

        body = resp.json()
        assert "checks" in body
        assert "noop_skill" in body["checks"]
        assert "total_duration_ms" in body

    def test_503_when_noop_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "deep2.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": False, "error": "sandbox failed"}),
        ):
            resp = client.get("/health/deep")

        assert resp.status_code == 503

    def test_deep_has_total_duration_ms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C6: resposta deep inclui total_duration_ms com latências."""
        db = tmp_path / "deep3.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 15, "exit_code": 0}),
        ):
            data = client.get("/health/deep").json()

        assert "total_duration_ms" in data
        assert data["total_duration_ms"] >= 0

    def test_deep_noop_duration_ms_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C6: noop_skill check inclui duration_ms."""
        db = tmp_path / "deep4.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 30, "exit_code": 0}),
        ):
            data = client.get("/health/deep").json()

        assert "duration_ms" in data["checks"]["noop_skill"]


# ── C5: Postgres up/down ──────────────────────────────────────────────────────

class TestPostgresC5:
    def test_503_when_postgres_pool_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C5: pool Postgres que falha → 503."""
        db = tmp_path / "c5.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        mock_pool = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=ConnectionRefusedError("pg down")
        )
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        app = FastAPI()
        app.include_router(make_health_router(get_db_pool=lambda: mock_pool))
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"]["postgres"]["ok"] is False

    def test_200_after_postgres_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C5: depois que Postgres volta (None=skipped), /ready retorna 200."""
        db = tmp_path / "c5b.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        # Sem Postgres → skipped → ok
        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
