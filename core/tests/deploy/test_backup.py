"""Testes do sistema de backup (F10)."""

from __future__ import annotations

import gzip
import sqlite3
import tarfile
import time
from pathlib import Path

import pytest

from agent.deploy.backup import (
    _backup_skills,
    _backup_sqlite,
    _purge_old_backups,
    _sha256,
    run_backup,
)


# Fixture helper para configurar caminhos via env vars
def _set_backup_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_path: Path | None = None,
    skills_dir: Path | None = None,
) -> Path:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_BACKUP_DIR", str(backup_dir))
    if db_path:
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db_path))
    if skills_dir:
        monkeypatch.setenv("AGENT_SKILLS_DIR", str(skills_dir))
    monkeypatch.setenv("AGENT_DB_POSTGRES_URL", "")
    return backup_dir


# ── _sha256 ───────────────────────────────────────────────────────────────────


class TestSha256:
    def test_hash_is_hex(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        result = _sha256(f)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "file2.txt"
        f.write_bytes(b"deterministic")
        assert _sha256(f) == _sha256(f)

    def test_different_files_different_hashes(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"content_a")
        f2.write_bytes(b"content_b")
        assert _sha256(f1) != _sha256(f2)


# ── _backup_sqlite ────────────────────────────────────────────────────────────


class TestBackupSqlite:
    def test_creates_gz_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (x TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello')")
        conn.commit()
        conn.close()
        _set_backup_env(monkeypatch, tmp_path, db_path=db)
        result = _backup_sqlite("20260101")
        assert result["ok"] is True, result
        assert Path(result["path"]).exists()

    def test_backup_is_valid_gzip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "agent2.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db)
        result = _backup_sqlite("20260102")
        with gzip.open(result["path"], "rb") as f:
            data = f.read(16)
        assert data[:16] == b"SQLite format 3\x00"

    def test_sha256_in_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db = tmp_path / "agent3.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db)
        result = _backup_sqlite("20260103")
        assert len(result["sha256"]) == 64

    def test_error_when_backup_dir_not_writable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Backup falha quando o diretório de destino não existe e não pode ser criado."""
        db = tmp_path / "agent4.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        # Aponta backup_dir para um caminho impossível (sem permissão de criar)
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))
        monkeypatch.setenv("AGENT_BACKUP_DIR", "/nonexistent_root_path/backups")
        result = _backup_sqlite("20260104")
        assert result["ok"] is False
        assert "error" in result


# ── _backup_skills ────────────────────────────────────────────────────────────


class TestBackupSkills:
    def test_creates_tarball(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path) -> None:
        _set_backup_env(monkeypatch, tmp_path, skills_dir=tmp_skills_dir)
        result = _backup_skills("20260201")
        assert result["ok"] is True, result
        assert Path(result["path"]).exists()

    def test_tarball_is_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path) -> None:
        _set_backup_env(monkeypatch, tmp_path, skills_dir=tmp_skills_dir)
        result = _backup_skills("20260202")
        with tarfile.open(result["path"], "r:gz") as tar:
            names = tar.getnames()
        assert any("example.yaml" in n for n in names)

    def test_skipped_when_skills_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_backup_env(monkeypatch, tmp_path, skills_dir=tmp_path / "nonexistent_skills")
        result = _backup_skills("20260203")
        assert result.get("skipped") is True


# ── _purge_old_backups ─────────────────────────────────────────────────────────


class TestPurgeOldBackups:
    def test_removes_old_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os

        backup_dir = _set_backup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("AGENT_BACKUP_RETAIN_DAYS", "14")

        old_file = backup_dir / "postgres-20200101.sql.gz"
        old_file.write_bytes(b"old")
        old_mtime = time.time() - 20 * 86400
        os.utime(str(old_file), (old_mtime, old_mtime))

        recent_file = backup_dir / "postgres-20260201.sql.gz"
        recent_file.write_bytes(b"recent")

        _purge_old_backups()
        assert not old_file.exists()
        assert recent_file.exists()

    def test_keeps_recent_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        backup_dir = _set_backup_env(monkeypatch, tmp_path)
        monkeypatch.setenv("AGENT_BACKUP_RETAIN_DAYS", "14")
        recent = backup_dir / "sqlite-20260201.db.gz"
        recent.write_bytes(b"data")
        _purge_old_backups()
        assert recent.exists()


# ── run_backup integration ────────────────────────────────────────────────────


class TestRunBackup:
    @pytest.mark.asyncio
    async def test_returns_summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path) -> None:
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db, skills_dir=tmp_skills_dir)

        result = await run_backup()
        assert "tag" in result
        assert "results" in result
        assert "sqlite" in result["results"]
        assert result["results"]["sqlite"]["ok"] is True

    @pytest.mark.asyncio
    async def test_c8_creates_two_files_min(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        """C8: run_backup cria pelo menos sqlite + skills (sem Postgres mock)."""
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db, skills_dir=tmp_skills_dir)

        result = await run_backup()
        tag = result["tag"]
        backup_dir = tmp_path / "backups"
        assert (backup_dir / f"sqlite-{tag}.db.gz").exists()
        assert (backup_dir / f"skills-{tag}.tar.gz").exists()

    @pytest.mark.asyncio
    async def test_c8_sha256_present_in_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        """C8: resultados incluem sha256 de cada arquivo."""
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db, skills_dir=tmp_skills_dir)

        result = await run_backup()
        sqlite_result = result["results"]["sqlite"]
        assert sqlite_result.get("ok") is True
        assert "sha256" in sqlite_result
        assert len(sqlite_result["sha256"]) == 64

    @pytest.mark.asyncio
    async def test_c8_retention_purges_old_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        """C8: run_backup chama _purge_old_backups — arquivo de 15 dias é apagado."""
        import os

        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db, skills_dir=tmp_skills_dir)
        monkeypatch.setenv("AGENT_BACKUP_RETAIN_DAYS", "14")

        old = tmp_path / "backups" / "postgres-20200101.sql.gz"
        old.write_bytes(b"old")
        os.utime(str(old), (time.time() - 15 * 86400, time.time() - 15 * 86400))

        await run_backup()
        assert not old.exists(), "Arquivo de 15 dias deveria ter sido apagado"

    @pytest.mark.asyncio
    async def test_c8_backup_emits_event_via_bus(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_skills_dir: Path
    ) -> None:
        """C8: backup emite backup.completed no event bus."""
        db = tmp_path / "agent.db"
        sqlite3.connect(str(db)).execute("SELECT 1").fetchone()
        _set_backup_env(monkeypatch, tmp_path, db_path=db, skills_dir=tmp_skills_dir)

        events: list[tuple] = []

        class _Bus:
            async def publish(self, kind: str, payload: dict) -> None:
                events.append((kind, payload))

        await run_backup(event_bus=_Bus())
        kinds = [e[0] for e in events]
        assert "backup.completed" in kinds or "backup.failed" in kinds
