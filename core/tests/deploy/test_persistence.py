"""Testes de persistência e migration idempotente (F10 — pré-requisito C1).

Verifica que:
- A migration 011_deploy.sql existe e é idempotente (IF NOT EXISTS em todos os CREATE)
- As tabelas deploy_events e worker_health têm as colunas esperadas
- O schema suporta todos os eventos do §8
- _db_record_event e _db_update_worker_health funcionam sem Postgres real
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

# ── Localização da migration ───────────────────────────────────────────────────


def _migration_path() -> Path:
    # core/tests/deploy/test_persistence.py → parents[2] = core/
    return Path(__file__).parents[2] / "migrations" / "011_deploy.sql"


class TestMigrationFile:
    def test_file_exists(self) -> None:
        assert _migration_path().exists(), "Migration 011_deploy.sql não encontrada"

    def test_all_creates_use_if_not_exists(self) -> None:
        content = _migration_path().read_text()
        creates = re.findall(r"CREATE\s+(TABLE|INDEX)\s+(\S+)", content, re.IGNORECASE)
        assert creates, "Nenhum CREATE encontrado na migration"
        for kind, name in creates:
            assert "IF NOT EXISTS" in content, f"CREATE {kind} {name} deve usar IF NOT EXISTS para idempotência"

    def test_deploy_events_table_present(self) -> None:
        content = _migration_path().read_text()
        assert "deploy_events" in content

    def test_worker_health_table_present(self) -> None:
        content = _migration_path().read_text()
        assert "worker_health" in content

    def test_indexes_present(self) -> None:
        content = _migration_path().read_text()
        assert "idx_deploy_events_ts" in content
        assert "idx_deploy_events_kind" in content


# ── Aplicação idempotente da migration ────────────────────────────────────────


class TestMigrationApply:
    def test_applies_twice_without_error(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        sql = _migration_path().read_text()
        conn = sqlite3.connect(str(db))
        conn.executescript(sql)
        conn.executescript(sql)  # segunda vez — não deve levantar
        conn.close()

    def test_deploy_events_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_migration_path().read_text())
        cols = [row[1] for row in conn.execute("PRAGMA table_info(deploy_events)").fetchall()]
        conn.close()
        assert "id" in cols
        assert "ts" in cols
        assert "kind" in cols
        assert "worker" in cols
        assert "detail" in cols
        assert "success" in cols

    def test_worker_health_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_migration_path().read_text())
        cols = [row[1] for row in conn.execute("PRAGMA table_info(worker_health)").fetchall()]
        conn.close()
        assert "worker" in cols
        assert "pid" in cols
        assert "started_at" in cols
        assert "last_seen" in cols
        assert "restarts" in cols
        assert "state" in cols

    def test_worker_health_has_primary_key(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_migration_path().read_text())
        pk_cols = [row[1] for row in conn.execute("PRAGMA table_info(worker_health)").fetchall() if row[5] > 0]
        conn.close()
        assert "worker" in pk_cols, "worker deve ser PK em worker_health"


# ── _db_record_event e _db_update_worker_health ───────────────────────────────


class TestDbHelpers:
    @pytest.fixture
    def db_with_schema(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(_migration_path().read_text())
        conn.close()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        return db

    def test_record_event_inserts_row(self, db_with_schema: Path) -> None:
        from agent.deploy.supervisor import _db_record_event

        _db_record_event("start", "orchestrator", {"pid": 1234}, True)

        conn = sqlite3.connect(str(db_with_schema))
        rows = conn.execute("SELECT kind, worker, success FROM deploy_events").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0] == ("start", "orchestrator", 1)

    def test_record_event_stores_json_detail(self, db_with_schema: Path) -> None:
        from agent.deploy.supervisor import _db_record_event

        detail = {"pid": 9999, "exit_code": -9}
        _db_record_event("crash", "api", detail, False)

        conn = sqlite3.connect(str(db_with_schema))
        row = conn.execute("SELECT detail FROM deploy_events WHERE kind='crash'").fetchone()
        conn.close()
        assert row is not None
        stored = json.loads(row[0])
        assert stored["pid"] == 9999
        assert stored["exit_code"] == -9

    def test_update_worker_health_upsert(self, db_with_schema: Path) -> None:
        from agent.deploy.supervisor import _db_update_worker_health

        _db_update_worker_health("orchestrator", 1234, 0.0, 0, "running")
        _db_update_worker_health("orchestrator", 5678, None, 1, "stopped")

        conn = sqlite3.connect(str(db_with_schema))
        row = conn.execute("SELECT pid, restarts, state FROM worker_health WHERE worker='orchestrator'").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 5678  # atualizado
        assert row[1] == 1
        assert row[2] == "stopped"

    def test_all_valid_event_kinds(self, db_with_schema: Path) -> None:
        """Todos os 11 event kinds do §8 podem ser inseridos."""
        from agent.deploy.supervisor import _db_record_event

        kinds = [
            "start",
            "stop",
            "crash",
            "restart",
            "backup",
            "restore",
            "upgrade",
        ]
        for kind in kinds:
            _db_record_event(kind, "orchestrator", {}, True)

        conn = sqlite3.connect(str(db_with_schema))
        count = conn.execute("SELECT COUNT(*) FROM deploy_events").fetchone()[0]
        conn.close()
        assert count == len(kinds)

    def test_record_event_silently_ignores_bad_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falha ao gravar evento não levanta exceção — supervisor não pode morrer por isso."""
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/path/agent.db")
        from agent.deploy.supervisor import _db_record_event

        _db_record_event("start", "api", {}, True)  # não deve levantar

    def test_worker_health_flapping_state(self, db_with_schema: Path) -> None:
        from agent.deploy.supervisor import _db_update_worker_health

        _db_update_worker_health("orchestrator", 0, None, 11, "flapping")

        conn = sqlite3.connect(str(db_with_schema))
        row = conn.execute("SELECT state, restarts FROM worker_health WHERE worker='orchestrator'").fetchone()
        conn.close()
        assert row[0] == "flapping"
        assert row[1] == 11
