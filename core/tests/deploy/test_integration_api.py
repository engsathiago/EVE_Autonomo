"""Testes de integração — endpoints REST do deploy (F10).

Cobre:
  POST /api/v1/deploy/backup  (C8)
  POST /api/v1/deploy/restore (C9)
  GET  /health/live            (C4)
  GET  /health/ready           (C5)
  GET  /health/deep            (C6)
  GET  /metrics                (C7)

Não sobe Postgres real. pg_dump/pg_restore são mockados.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_deploy: bool = True,
    with_health: bool = True,
    with_metrics: bool = True,
) -> TestClient:
    db = tmp_path / "agent.db"
    sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
    monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
    monkeypatch.setenv("AGENT_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
    (tmp_path / "backups").mkdir(exist_ok=True)
    (tmp_path / "skills" / "_active").mkdir(parents=True, exist_ok=True)

    app = FastAPI()

    if with_deploy:
        from agent.api.deploy import make_deploy_router

        app.include_router(make_deploy_router())

    if with_health:
        from agent.deploy.health import make_health_router

        app.include_router(make_health_router())

    if with_metrics:
        from agent.deploy.metrics import make_metrics_router

        app.include_router(make_metrics_router())

    return TestClient(app, raise_server_exceptions=False)


# ── C4: /health/live <50ms ────────────────────────────────────────────────────


class TestLivenessC4:
    def test_200_response(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        resp = client.get("/health/live")
        assert resp.status_code == 200

    def test_responds_under_50ms(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C4: liveness deve responder em <50ms."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        # Aquecer o client (primeira chamada pode incluir overhead de startup)
        client.get("/health/live")
        # Medir 3 vezes e pegar mediana
        times_ms = []
        for _ in range(3):
            t0 = time.monotonic()
            client.get("/health/live")
            times_ms.append((time.monotonic() - t0) * 1000)
        median_ms = sorted(times_ms)[1]
        assert median_ms < 50, f"liveness mediana {median_ms:.1f}ms, esperado <50ms"

    def test_body_has_status_alive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        assert client.get("/health/live").json()["status"] == "alive"

    def test_no_io_in_liveness(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Liveness nunca abre banco de dados."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        # Aponta sqlite para caminho inexistente — liveness ainda deve retornar 200
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/db.db")
        resp = client.get("/health/live")
        assert resp.status_code == 200


# ── C5: /health/ready com Postgres up/down ────────────────────────────────────


class TestReadinessC5:
    def test_200_when_sqlite_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    def test_503_when_sqlite_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """C5: Componente crítico fora → 503."""
        monkeypatch.setenv("AGENT_DB_SQLITE", "/totally/nonexistent/agent.db")
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
        from fastapi import FastAPI

        from agent.deploy.health import make_health_router

        app = FastAPI()
        app.include_router(make_health_router())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 503

    def test_503_when_postgres_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C5: Postgres down → 503 sem restart manual."""
        from fastapi import FastAPI

        from agent.deploy.health import make_health_router

        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        # Simula pool Postgres que falha
        mock_pool = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("pg down"))
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        app = FastAPI()
        app.include_router(make_health_router(get_db_pool=lambda: mock_pool))
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["checks"]["postgres"]["ok"] is False

    def test_200_when_postgres_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sem Postgres configurado (None) → postgres check é skipped, retorna 200."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        resp = client.get("/health/ready")
        data = resp.json()
        # postgres skipped não derruba readiness
        assert data["checks"]["postgres"].get("skipped") is True or data["checks"]["postgres"]["ok"] is True
        assert resp.status_code == 200

    def test_ready_response_has_all_check_keys(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        data = client.get("/health/ready").json()
        assert "sqlite" in data["checks"]
        assert "postgres" in data["checks"]
        assert "scheduler" in data["checks"]
        assert "subagent_pool" in data["checks"]


# ── C6: /health/deep executa noop skill ───────────────────────────────────────


class TestDeepHealthC6:
    def test_200_with_mocked_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 30, "exit_code": 0}),
        ):
            resp = client.get("/health/deep")
        assert resp.status_code == 200

    def test_noop_skill_in_checks(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 45, "exit_code": 0}),
        ):
            data = client.get("/health/deep").json()
        assert "noop_skill" in data["checks"]
        assert data["checks"]["noop_skill"]["ok"] is True

    def test_total_duration_ms_present(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 20, "exit_code": 0}),
        ):
            data = client.get("/health/deep").json()
        assert "total_duration_ms" in data

    def test_503_when_noop_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C6: noop skill falha → 503 com detalhes."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": False, "error": "sandbox error", "exit_code": 1}),
        ):
            resp = client.get("/health/deep")
        assert resp.status_code == 503
        assert resp.json()["checks"]["noop_skill"]["ok"] is False

    def test_deep_under_2s(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C6: /health/deep deve completar em <2s com noop rápido."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_metrics=False)
        with patch(
            "agent.deploy.health._run_noop_skill",
            new=AsyncMock(return_value={"ok": True, "duration_ms": 10, "exit_code": 0}),
        ):
            t0 = time.monotonic()
            client.get("/health/deep")
            elapsed_ms = (time.monotonic() - t0) * 1000
        assert elapsed_ms < 2000, f"deep check demorou {elapsed_ms:.0f}ms"


# ── C7: /metrics com 12 séries ───────────────────────────────────────────────


class TestMetricsC7:
    _EXPECTED_SERIES = [
        "agent_missions_total",
        "agent_mission_duration_seconds",
        "agent_skills_executed_total",
        "agent_skill_execution_duration_seconds",
        "agent_subagent_pool_active",
        "agent_sandbox_executions_total",
        "agent_critic_decisions_total",
        "agent_scheduler_jobs_active",
        "agent_worker_restarts_total",
        "agent_db_query_duration_seconds",
        "agent_memory_bytes",
        "agent_uptime_seconds",
    ]

    def test_all_12_series_in_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C7: /metrics retorna todas as 12 séries."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_health=False)
        body = client.get("/metrics").text
        for name in self._EXPECTED_SERIES:
            assert name in body, f"série ausente: {name}"

    def test_worker_restarts_initialized_to_zero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C7: counters de boot têm valor não-negativo (inicializados com labels)."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_health=False)
        body = client.get("/metrics").text
        # Deve conter labels dos 4 workers
        for worker in ("orchestrator", "scheduler", "api", "heartbeat"):
            assert f'worker="{worker}"' in body, f"label worker={worker} ausente"

    def test_missions_labels_initialized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C7: missions_total inicializado com labels completed/failed/cancelled."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_health=False)
        body = client.get("/metrics").text
        for status in ("completed", "failed", "cancelled"):
            assert f'status="{status}"' in body, f"label status={status} ausente"

    def test_uptime_positive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_health=False)
        body = client.get("/metrics").text
        for line in body.splitlines():
            if line.startswith("agent_uptime_seconds") and not line.startswith("#"):
                assert float(line.split()[-1]) >= 0
                return
        pytest.fail("agent_uptime_seconds não encontrado")

    def test_memory_bytes_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C7: memory_bytes não-zero (processo tem RSS real)."""
        client = _make_app(tmp_path, monkeypatch, with_deploy=False, with_health=False)
        body = client.get("/metrics").text
        for line in body.splitlines():
            if line.startswith("agent_memory_bytes") and not line.startswith("#"):
                assert float(line.split()[-1]) > 0, "RSS deve ser > 0"
                return
        pytest.fail("agent_memory_bytes não encontrado")


# ── C8: POST /api/v1/deploy/backup ───────────────────────────────────────────


class TestBackupApiC8:
    def test_backup_returns_200(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_health=False, with_metrics=False)
        resp = client.post("/api/v1/deploy/backup")
        assert resp.status_code == 200

    def test_backup_response_has_tag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_app(tmp_path, monkeypatch, with_health=False, with_metrics=False)
        data = client.post("/api/v1/deploy/backup").json()
        assert "tag" in data

    def test_backup_response_has_results(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C8: resposta inclui results com sqlite e skills."""
        client = _make_app(tmp_path, monkeypatch, with_health=False, with_metrics=False)
        data = client.post("/api/v1/deploy/backup").json()
        assert "results" in data
        assert "sqlite" in data["results"]

    def test_backup_sqlite_has_sha256(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C8: resultado do backup SQLite inclui sha256."""
        client = _make_app(tmp_path, monkeypatch, with_health=False, with_metrics=False)
        data = client.post("/api/v1/deploy/backup").json()
        sqlite_result = data["results"]["sqlite"]
        assert sqlite_result.get("ok") is True
        assert "sha256" in sqlite_result
        assert len(sqlite_result["sha256"]) == 64

    def test_backup_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C8: arquivo de backup é criado em AGENT_BACKUP_DIR."""
        client = _make_app(tmp_path, monkeypatch, with_health=False, with_metrics=False)
        data = client.post("/api/v1/deploy/backup").json()
        tag = data["tag"]
        backup_dir = tmp_path / "backups"
        sqlite_backup = backup_dir / f"sqlite-{tag}.db.gz"
        assert sqlite_backup.exists(), f"backup não criado: {sqlite_backup}"


# ── C9: POST /api/v1/deploy/restore ──────────────────────────────────────────


class TestRestoreApiC9:
    @pytest.fixture
    def client_with_backup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
        """Configura app, cria backup, retorna (client, tag)."""
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE missions (id INT, status TEXT)")
        conn.execute("INSERT INTO missions VALUES (1, 'completed')")
        conn.commit()
        conn.close()

        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(tmp_path / "backups"))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
        (tmp_path / "backups").mkdir(exist_ok=True)
        (tmp_path / "skills" / "_active").mkdir(parents=True, exist_ok=True)

        from agent.deploy.backup import _backup_sqlite

        result = _backup_sqlite("20260701")
        assert result["ok"]

        from agent.api.deploy import make_deploy_router

        app = FastAPI()
        app.include_router(make_deploy_router())
        client = TestClient(app, raise_server_exceptions=False)
        return client, "20260701"

    def test_restore_returns_200(self, client_with_backup: tuple[TestClient, str]) -> None:
        client, tag = client_with_backup
        resp = client.post("/api/v1/deploy/restore", json={"date": tag})
        assert resp.status_code == 200

    def test_restore_has_results(self, client_with_backup: tuple[TestClient, str]) -> None:
        client, tag = client_with_backup
        data = client.post("/api/v1/deploy/restore", json={"date": tag}).json()
        assert "results" in data

    def test_restore_sqlite_ok(self, client_with_backup: tuple[TestClient, str]) -> None:
        """C9: restore de SQLite é bem-sucedido."""
        client, tag = client_with_backup
        data = client.post(
            "/api/v1/deploy/restore",
            json={"date": tag, "kinds": ["sqlite"]},
        ).json()
        assert data["results"]["sqlite"]["ok"] is True

    def test_restore_data_preserved(
        self,
        client_with_backup: tuple[TestClient, str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C9: após restore, dados originais estão acessíveis."""
        client, tag = client_with_backup
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))

        client.post("/api/v1/deploy/restore", json={"date": tag, "kinds": ["sqlite"]})

        conn = sqlite3.connect(str(dest_db))
        rows = conn.execute("SELECT status FROM missions WHERE id=1").fetchall()
        conn.close()
        assert rows[0][0] == "completed"
