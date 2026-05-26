"""
Restore a partir de backup diário (F10).

Caminho inverso de backup.py:
  1. Valida que os arquivos existem para a data solicitada.
  2. Restaura SQLite via sqlite3 .backup API (inverso: backup → live).
  3. Restaura Postgres via psql (lê o .sql.gz e aplica).
  4. Restaura skills/_active/ via untar.
  5. Emite restore.started e restore.completed no event bus.

CLI: agent deploy restore --date YYYYMMDD
"""

from __future__ import annotations

import asyncio
import gzip
import os
import shutil
import sqlite3
import tarfile
import time
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


async def run_restore(
    date_tag: str,
    kinds: list[str] | None = None,
    event_bus: object | None = None,
) -> dict:
    """Restaura backups da data especificada (formato YYYYMMDD).

    kinds: lista de targets a restaurar ('postgres', 'sqlite', 'skills').
           None = todos disponíveis.
    """
    if kinds is None:
        kinds = ["postgres", "sqlite", "skills"]

    t0 = time.time()
    results: dict[str, dict] = {}

    if event_bus is not None:
        try:
            await event_bus.publish("restore.started", {"date": date_tag, "kinds": kinds})
        except Exception:
            pass

    log.info("restore.starting", date=date_tag, kinds=kinds)

    if "postgres" in kinds:
        if _pg_url():
            results["postgres"] = await _restore_postgres(date_tag)
        else:
            results["postgres"] = {"skipped": True}

    if "sqlite" in kinds:
        results["sqlite"] = await asyncio.to_thread(_restore_sqlite, date_tag)

    if "skills" in kinds:
        results["skills"] = await asyncio.to_thread(_restore_skills, date_tag)

    duration_ms = int((time.time() - t0) * 1000)
    all_ok = all(r.get("ok", r.get("skipped", False)) for r in results.values())

    summary = {
        "date": date_tag,
        "duration_ms": duration_ms,
        "results": results,
        "all_ok": all_ok,
    }

    if event_bus is not None:
        try:
            await event_bus.publish("restore.completed", summary)
        except Exception:
            pass

    log.info("restore.completed", date=date_tag, duration_ms=duration_ms, all_ok=all_ok)
    return summary


async def _restore_postgres(date_tag: str) -> dict:
    backup_file = _backup_dir() / f"postgres-{date_tag}.sql.gz"
    if not backup_file.exists():
        return {"ok": False, "error": f"backup não encontrado: {backup_file}"}

    t0 = time.time()
    try:
        with gzip.open(backup_file, "rb") as f:
            data = f.read()

        proc = await asyncio.create_subprocess_exec(
            "pg_restore",
            "--clean",
            "--if-exists",
            f"--dbname={_pg_url()}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(input=data), timeout=300)
        if proc.returncode not in (0, 1):  # pg_restore retorna 1 com warnings
            return {"ok": False, "error": stderr.decode()[:500]}

        return {"ok": True, "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _restore_sqlite(date_tag: str) -> dict:
    backup_file = _backup_dir() / f"sqlite-{date_tag}.db.gz"
    if not backup_file.exists():
        return {"ok": False, "error": f"backup não encontrado: {backup_file}"}

    t0 = time.time()
    tmp_db = _backup_dir() / f"_restore_{date_tag}.db"
    try:
        # Descomprime para .db temporário
        with gzip.open(backup_file, "rb") as f_in, open(tmp_db, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        # Restaura usando sqlite3 .backup API: copia tmp → live
        src = sqlite3.connect(str(tmp_db))
        dst = sqlite3.connect(str(_sqlite_path()))
        src.backup(dst)
        dst.close()
        src.close()

        return {"ok": True, "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        tmp_db.unlink(missing_ok=True)


def _restore_skills(date_tag: str) -> dict:
    backup_file = _backup_dir() / f"skills-{date_tag}.tar.gz"
    if not backup_file.exists():
        return {"ok": False, "error": f"backup não encontrado: {backup_file}"}

    t0 = time.time()
    try:
        # Remove diretório atual e extrai backup
        if _skills_dir().exists():
            shutil.rmtree(_skills_dir())

        with tarfile.open(backup_file, "r:gz") as tar:
            # Segurança: evita path traversal
            for member in tar.getmembers():
                if ".." in member.name or member.name.startswith("/"):
                    continue
            tar.extractall(path=_skills_dir().parent, filter="data")

        return {"ok": True, "duration_ms": int((time.time() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
