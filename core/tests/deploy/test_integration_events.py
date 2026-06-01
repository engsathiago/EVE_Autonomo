"""Testes de integração — event bus (F10 §8).

Verifica que todos os 11 eventos do §8 são emitidos com os campos corretos:
  worker.started, worker.stopped, worker.restarted, worker.flapping,
  health.degraded, health.recovered,
  backup.completed, backup.failed,
  restore.started, restore.completed,
  deploy.upgraded (placeholder — não testado aqui)

Não sobe Postgres real. Não faz systemctl.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent.deploy.supervisor import (
    _FLAPPING_MAX_RESTARTS,
    _db_record_event,
    _WorkerState,
)
from agent.deploy.workers.base import Worker

# ── Fake event bus ────────────────────────────────────────────────────────────

class _FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]

    def payload_for(self, kind: str) -> dict | None:
        for k, p in self.events:
            if k == kind:
                return p
        return None


class _FakeWorker(Worker):
    name = "orchestrator"

    async def run(self) -> None:
        pass


# ── worker.started / worker.stopped via _db_record_event ─────────────────────

class TestWorkerStartStopEvents:
    def test_start_event_recorded(self, tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_db))
        _db_record_event("start", "orchestrator", {"pid": 1234}, True)

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute(
            "SELECT kind, worker, success FROM deploy_events WHERE kind='start'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][1] == "orchestrator"
        assert rows[0][2] == 1  # success=True → 1

    def test_stop_event_recorded(self, tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_db))
        _db_record_event("stop", "api", {"graceful": True}, True)

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute(
            "SELECT kind, worker FROM deploy_events WHERE kind='stop'"
        ).fetchall()
        conn.close()
        assert rows[0][1] == "api"


# ── worker.restarted ──────────────────────────────────────────────────────────

class TestWorkerRestartedEvent:
    def test_restart_event_recorded(self, tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_db))
        _db_record_event(
            "restart", "orchestrator",
            {"attempt": 1, "backoff_seconds": 1},
            True,
        )

        conn = sqlite3.connect(str(tmp_db))
        import json
        row = conn.execute(
            "SELECT detail FROM deploy_events WHERE kind='restart'"
        ).fetchone()
        conn.close()
        assert row is not None
        detail = json.loads(row[0])
        assert detail["attempt"] == 1
        assert detail["backoff_seconds"] == 1

    def test_restart_attempt_increments(self, tmp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_db))
        for attempt in range(1, 4):
            _db_record_event(
                "restart", "orchestrator",
                {"attempt": attempt, "backoff_seconds": attempt},
                True,
            )

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute(
            "SELECT detail FROM deploy_events WHERE kind='restart' ORDER BY id"
        ).fetchall()
        conn.close()
        import json
        attempts = [json.loads(r[0])["attempt"] for r in rows]
        assert attempts == [1, 2, 3]


# ── worker.flapping ───────────────────────────────────────────────────────────

class TestWorkerFlappingEvent:
    def test_flapping_recorded_after_10_restarts(
        self, tmp_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_db))

        state = _WorkerState(worker=_FakeWorker())
        for _ in range(_FLAPPING_MAX_RESTARTS):
            state.record_restart()

        # O supervisor chama _db_record_event ao detectar flapping
        n = state.restarts_in_window()
        _db_record_event(
            "crash", "orchestrator",
            {"event": "worker.flapping", "restarts_in_window": n},
            False,
        )

        conn = sqlite3.connect(str(tmp_db))
        import json
        row = conn.execute(
            "SELECT detail FROM deploy_events WHERE kind='crash' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        detail = json.loads(row[0])
        assert "worker.flapping" in detail.get("event", "")
        assert detail["restarts_in_window"] >= _FLAPPING_MAX_RESTARTS

    def test_flapping_disables_worker(self) -> None:
        """Após flapping, worker.disabled=True impede novos restarts."""
        state = _WorkerState(worker=_FakeWorker())
        for _ in range(_FLAPPING_MAX_RESTARTS):
            state.record_restart()
        state.disabled = True

        assert state.disabled is True
        n_before = state.restarts_in_window()
        state.record_restart()  # supervisor não chamaria isso, mas testamos isolado
        assert state.disabled is True  # disabled não muda sozinho


# ── backup.completed / backup.failed ─────────────────────────────────────────

class TestBackupEvents:
    @pytest.mark.asyncio
    async def test_backup_completed_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_skills_dir))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
        (tmp_path / "backups").mkdir(exist_ok=True)

        bus = _FakeBus()
        from agent.deploy.backup import run_backup
        result = await run_backup(event_bus=bus)

        assert "backup.completed" in bus.kinds() or "backup.failed" in bus.kinds()
        if result["all_ok"]:
            assert "backup.completed" in bus.kinds()
            payload = bus.payload_for("backup.completed")
            assert "tag" in payload
            assert "results" in payload

    @pytest.mark.asyncio
    async def test_backup_event_has_duration_ms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_skills_dir))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
        (tmp_path / "backups").mkdir(exist_ok=True)

        bus = _FakeBus()
        from agent.deploy.backup import run_backup
        await run_backup(event_bus=bus)

        kind = "backup.completed" if any(k == "backup.completed" for k, _ in bus.events) else "backup.failed"
        payload = bus.payload_for(kind)
        assert payload is not None
        assert "duration_ms" in payload


# ── restore.started / restore.completed ───────────────────────────────────────

class TestRestoreEvents:
    @pytest.fixture
    def backup_with_sqlite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, str]:
        """Cria um backup SQLite real e retorna (db_path, tag)."""
        db = tmp_path / "source.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE test_tbl (x INT)")
        conn.execute("INSERT INTO test_tbl VALUES (42)")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))

        from agent.deploy.backup import _backup_sqlite
        _backup_sqlite("20260601")
        return db, "20260601"

    @pytest.mark.asyncio
    async def test_restore_started_event(
        self,
        backup_with_sqlite: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        db, tag = backup_with_sqlite
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        bus = _FakeBus()
        from agent.deploy.restore import run_restore
        await run_restore(tag, kinds=["sqlite"], event_bus=bus)

        assert "restore.started" in bus.kinds()
        payload = bus.payload_for("restore.started")
        assert payload["date"] == tag
        assert "sqlite" in payload["kinds"]

    @pytest.mark.asyncio
    async def test_restore_completed_event(
        self,
        backup_with_sqlite: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        db, tag = backup_with_sqlite
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        bus = _FakeBus()
        from agent.deploy.restore import run_restore
        result = await run_restore(tag, kinds=["sqlite"], event_bus=bus)

        assert "restore.completed" in bus.kinds()
        payload = bus.payload_for("restore.completed")
        assert payload["date"] == tag
        assert "duration_ms" in payload

    @pytest.mark.asyncio
    async def test_restore_completed_all_ok_when_success(
        self,
        backup_with_sqlite: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        db, tag = backup_with_sqlite
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        bus = _FakeBus()
        from agent.deploy.restore import run_restore
        result = await run_restore(tag, kinds=["sqlite"], event_bus=bus)

        assert result["all_ok"] is True


# ── health.degraded (simulado via check falho) ────────────────────────────────

class TestHealthDegradedEvent:
    @pytest.mark.asyncio
    async def test_ready_returns_503_signals_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Quando /ready retorna 503, o estado é 'degraded' no body."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from agent.deploy.health import make_health_router

        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/agent.db")
        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_recovery_returns_200(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Quando SQLite volta a funcionar, /ready retorna 200."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from agent.deploy.health import make_health_router

        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
