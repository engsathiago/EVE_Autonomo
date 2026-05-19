"""
Backup automático (F10): Postgres, SQLite e skills/_active/.

Cria 3 arquivos em AGENT_BACKUP_DIR:
  postgres-YYYYMMDD.sql.gz   (pg_dump --format=custom)
  sqlite-YYYYMMDD.db.gz      (sqlite3 .backup API + gzip)
  skills-YYYYMMDD.tar.gz     (tar czf do diretório skills)

Emite evento backup.completed ou backup.failed no event bus quando disponível.
Retenção: apaga arquivos com mais de AGENT_BACKUP_RETAIN_DAYS dias.

O job é registrado no APScheduler da F6 pelo server.py.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import date
from pathlib import Path

from agent.observability.logger import get_logger

log = get_logger(__name__)

def _backup_dir() -> Path:
    return Path(os.environ.get("AGENT_BACKUP_DIR", "/var/lib/agent/backups"))

def _sqlite_path() -> Path:
    return Path(os.environ.get("AGENT_DB_SQLITE", "agent.db"))

def _skills_dir() -> Path:
    return Path(os.environ.get("AGENT_SKILLS_DIR", "/var/lib/agent/data/skills"))

def _pg_url() -> str:
    return os.environ.get("AGENT_DB_POSTGRES_URL", "")

def _retain_days() -> int:
    return int(os.environ.get("AGENT_BACKUP_RETAIN_DAYS", "14"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def run_backup(event_bus: object | None = None) -> dict:
    """Executa backup completo dos 3 targets. Retorna sumário."""
    tag = date.today().strftime("%Y%m%d")
    _backup_dir().mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    results: dict[str, dict] = {}

    # Postgres
    if _pg_url():
        results["postgres"] = await _backup_postgres(tag)
    else:
        results["postgres"] = {"skipped": True}

    # SQLite
    results["sqlite"] = await asyncio.to_thread(_backup_sqlite, tag)

    # Skills
    results["skills"] = await asyncio.to_thread(_backup_skills, tag)

    duration_ms = int((time.time() - t0) * 1000)
    all_ok = all(
        r.get("ok", r.get("skipped", False)) for r in results.values()
    )

    # Retenção
    await asyncio.to_thread(_purge_old_backups)

    summary = {
        "tag": tag,
        "duration_ms": duration_ms,
        "results": results,
        "all_ok": all_ok,
    }

    kind = "backup.completed" if all_ok else "backup.failed"
    if event_bus is not None:
        try:
            await event_bus.publish(kind, summary)  # type: ignore[attr-defined]
        except Exception:
            pass

    log.info(kind, tag=tag, duration_ms=duration_ms, all_ok=all_ok)
    return summary


async def _backup_postgres(tag: str) -> dict:
    out = _backup_dir() / f"postgres-{tag}.sql.gz"
    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--format=custom",
            _pg_url(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            return {"ok": False, "error": stderr.decode()[:500]}

        with gzip.open(out, "wb") as f:
            f.write(stdout)

        return {
            "ok": True,
            "path": str(out),
            "size_bytes": out.stat().st_size,
            "sha256": _sha256(out),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _backup_sqlite(tag: str) -> dict:
    """Usa a API sqlite3.Connection.backup() — snapshot consistente sem lock."""
    out_db = _backup_dir() / f"sqlite-{tag}.db"
    out = _backup_dir() / f"sqlite-{tag}.db.gz"
    t0 = time.time()
    try:
        src = sqlite3.connect(str(_sqlite_path()))
        dst = sqlite3.connect(str(out_db))
        src.backup(dst)  # sqlite3 .backup API nativa
        dst.close()
        src.close()

        # Gzip do arquivo de snapshot
        with open(out_db, "rb") as f_in, gzip.open(out, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        out_db.unlink()  # remove o .db temporário

        return {
            "ok": True,
            "path": str(out),
            "size_bytes": out.stat().st_size,
            "sha256": _sha256(out),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _backup_skills(tag: str) -> dict:
    out = _backup_dir() / f"skills-{tag}.tar.gz"
    t0 = time.time()
    try:
        if not _skills_dir().exists():
            return {"ok": True, "skipped": True, "reason": "skills dir not found"}

        with tarfile.open(out, "w:gz") as tar:
            tar.add(_skills_dir(), arcname="skills")

        return {
            "ok": True,
            "path": str(out),
            "size_bytes": out.stat().st_size,
            "sha256": _sha256(out),
            "duration_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _purge_old_backups() -> None:
    """Apaga arquivos de backup com mais de RETAIN_DAYS dias."""
    cutoff = time.time() - _retain_days() * 86400
    for path in _backup_dir().glob("*.gz"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            log.info("backup.purged", path=str(path))
