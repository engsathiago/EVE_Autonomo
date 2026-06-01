"""Testes do sistema de restore (F10)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from agent.deploy.restore import _restore_skills, _restore_sqlite, run_restore


def _make_sqlite_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tag: str,
) -> Path:
    """Cria backup de SQLite na tmp_path e retorna o caminho do arquivo."""
    db = tmp_path / "source.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE kv (k TEXT, v TEXT)")
    conn.execute("INSERT INTO kv VALUES ('hello', 'world')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
    monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))

    from agent.deploy.backup import _backup_sqlite

    result = _backup_sqlite(tag)
    assert result["ok"], result
    return db


# ── _restore_sqlite ───────────────────────────────────────────────────────────


class TestRestoreSqlite:
    def test_restores_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        source_db = _make_sqlite_backup(monkeypatch, tmp_path, "20260301")

        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))

        result = _restore_sqlite("20260301")
        assert result["ok"] is True, result

        conn = sqlite3.connect(str(dest_db))
        rows = conn.execute("SELECT v FROM kv WHERE k='hello'").fetchall()
        conn.close()
        assert rows[0][0] == "world"

    def test_error_when_backup_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        backup_dir = tmp_path / "empty"
        backup_dir.mkdir()
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_path / "dest.db"))

        result = _restore_sqlite("99991231")
        assert result["ok"] is False
        assert "backup não encontrado" in result["error"]

    def test_duration_ms_in_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_sqlite_backup(monkeypatch, tmp_path, "20260302")
        dest_db = tmp_path / "dest2.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))

        result = _restore_sqlite("20260302")
        assert "duration_ms" in result


# ── _restore_skills ───────────────────────────────────────────────────────────


class TestRestoreSkills:
    def test_restores_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_skills_dir: Path,
    ) -> None:
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_skills_dir))

        from agent.deploy.backup import _backup_skills

        _backup_skills("20260401")

        # Remove o diretório de skills para simular restauração
        shutil.rmtree(tmp_skills_dir)

        # Aponta para o mesmo local (será recriado pelo restore)
        result = _restore_skills("20260401")
        assert result["ok"] is True, result
        assert (tmp_skills_dir.parent / "skills" / "_active" / "example.yaml").exists()

    def test_error_when_backup_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        backup_dir = tmp_path / "empty"
        backup_dir.mkdir()
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_path / "skills"))

        result = _restore_skills("99991231")
        assert result["ok"] is False


# ── run_restore ───────────────────────────────────────────────────────────────


class TestRunRestore:
    @pytest.mark.asyncio
    async def test_returns_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_skills_dir: Path,
    ) -> None:
        source_db = _make_sqlite_backup(monkeypatch, tmp_path, "20260501")

        backup_dir = tmp_path / "backups"
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(tmp_skills_dir))

        from agent.deploy.backup import _backup_skills

        _backup_skills("20260501")

        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        result = await run_restore("20260501", kinds=["sqlite", "skills"])
        assert "results" in result
        assert result["results"]["sqlite"]["ok"] is True

    @pytest.mark.asyncio
    async def test_emits_event_on_bus(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Emite restore.completed no event bus."""
        source_db = _make_sqlite_backup(monkeypatch, tmp_path, "20260601")
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        events: list[tuple] = []

        class FakeBus:
            async def publish(self, kind: str, payload: dict) -> None:
                events.append((kind, payload))

        result = await run_restore("20260601", kinds=["sqlite"], event_bus=FakeBus())
        kinds = [e[0] for e in events]
        assert "restore.started" in kinds
        assert "restore.completed" in kinds

    @pytest.mark.asyncio
    async def test_c9_round_trip_preserves_row_count(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C9: round-trip backup→restore preserva contagem de missões."""
        db = tmp_path / "source.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE missions (id INT, status TEXT)")
        for i in range(5):
            conn.execute(f"INSERT INTO missions VALUES ({i}, 'completed')")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))

        from agent.deploy.backup import _backup_sqlite

        result = _backup_sqlite("20260701")
        assert result["ok"]

        dest_db = tmp_path / "restored.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        restore_result = await run_restore("20260701", kinds=["sqlite"])
        assert restore_result["all_ok"] is True

        conn = sqlite3.connect(str(dest_db))
        count = conn.execute("SELECT COUNT(*) FROM missions WHERE status='completed'").fetchone()[0]
        conn.close()
        assert count == 5

    @pytest.mark.asyncio
    async def test_c9_restore_emits_started_and_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C9: emite restore.started e restore.completed com campos corretos."""
        source_db = _make_sqlite_backup(monkeypatch, tmp_path, "20260801")
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        events: list[tuple] = []

        class _Bus:
            async def publish(self, kind: str, payload: dict) -> None:
                events.append((kind, payload))

        await run_restore("20260801", kinds=["sqlite"], event_bus=_Bus())
        event_map = {k: p for k, p in events}

        assert "restore.started" in event_map
        assert event_map["restore.started"]["date"] == "20260801"

        assert "restore.completed" in event_map
        assert "duration_ms" in event_map["restore.completed"]
        assert event_map["restore.completed"]["all_ok"] is True

    @pytest.mark.asyncio
    async def test_c9_result_has_duration_ms(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """C9: resultado do restore inclui duration_ms."""
        _make_sqlite_backup(monkeypatch, tmp_path, "20260901")
        dest_db = tmp_path / "dest.db"
        monkeypatch.setenv("AGENT_DB_SQLITE", str(dest_db))
        monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")

        result = await run_restore("20260901", kinds=["sqlite"])
        assert "duration_ms" in result
        assert result["duration_ms"] >= 0
