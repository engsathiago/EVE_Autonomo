"""Fixtures compartilhadas para os testes de deploy."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """SQLite temporário com schema de deploy."""
    db = tmp_path / "agent.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deploy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            kind TEXT NOT NULL,
            worker TEXT,
            detail TEXT,
            success BOOLEAN NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_deploy_events_ts ON deploy_events(ts);
        CREATE INDEX IF NOT EXISTS idx_deploy_events_kind ON deploy_events(kind);
        CREATE TABLE IF NOT EXISTS worker_health (
            worker TEXT PRIMARY KEY,
            pid INTEGER,
            started_at TIMESTAMP,
            last_seen TIMESTAMP,
            restarts INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'stopped'
        );
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def tmp_backup_dir(tmp_path: Path) -> Path:
    d = tmp_path / "backups"
    d.mkdir()
    return d


@pytest.fixture
def tmp_skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    (d / "_active").mkdir(parents=True)
    (d / "_active" / "example.yaml").write_text("slug: example\n")
    return d
