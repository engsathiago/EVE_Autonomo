"""
SandboxRegistry: rastreia execuções ativas e persiste registros no banco.

Cada execução gera 1 linha em sandbox_executions. Stdout/stderr completos
são escritos em logs/sandbox/<id>.{out,err} com rotação por dia.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.sandbox.base import SandboxResult

log = get_logger(__name__)

_LOG_DIR = Path("logs/sandbox")
_RETENTION_DAYS = 7


class SandboxRegistry:
    def __init__(self, db_pool: Any | None = None, log_dir: Path = _LOG_DIR) -> None:
        self._pool = db_pool
        self._log_dir = log_dir
        self._active: dict[str, dict[str, Any]] = {}

    def new_id(self) -> str:
        return uuid4().hex

    def command_hash(self, command: list[str] | str) -> str:
        raw = command if isinstance(command, str) else " ".join(command)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def command_preview(self, command: list[str] | str) -> str:
        raw = command if isinstance(command, str) else " ".join(command)
        return raw[:200]

    def mark_started(
        self,
        sandbox_id: str,
        policy_name: str,
        backend: str,
        command: list[str] | str,
    ) -> None:
        self._active[sandbox_id] = {
            "policy_name": policy_name,
            "backend": backend,
            "command_hash": self.command_hash(command),
            "command_preview": self.command_preview(command),
            "started_at": time.monotonic(),
        }

    def mark_done(self, sandbox_id: str) -> None:
        self._active.pop(sandbox_id, None)

    def active_count(self) -> int:
        return len(self._active)

    async def record(
        self,
        sandbox_id: str,
        policy_name: str,
        backend: str,
        command: list[str] | str,
        result: "SandboxResult",
        mission_id: str | None = None,
        subagent_id: str | None = None,
    ) -> None:
        # Persiste logs em arquivo
        await self._write_logs(sandbox_id, result.stdout, result.stderr)

        if self._pool is None:
            return

        try:
            await self._pool.execute(
                """
                INSERT INTO sandbox_executions (
                    id, created_at, policy_name, backend, command_hash, command_preview,
                    exit_code, duration_ms, memory_peak_mb, cpu_seconds,
                    timed_out, oom_killed, network_denied_count,
                    mission_id, subagent_id, stdout_preview, stderr_preview
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13,
                    $14, $15, $16, $17
                )
                """,
                sandbox_id,
                datetime.now(tz=timezone.utc),
                policy_name,
                backend,
                self.command_hash(command),
                self.command_preview(command),
                result.exit_code,
                result.duration_ms,
                result.memory_peak_mb,
                result.cpu_seconds,
                result.timed_out,
                result.oom_killed,
                len(result.network_denied_attempts),
                mission_id,
                subagent_id,
                result.stdout[:500],
                result.stderr[:500],
            )
        except Exception as exc:
            log.warning("sandbox.registry.persist_failed", error=str(exc))

    async def _write_logs(self, sandbox_id: str, stdout: str, stderr: str) -> None:
        try:
            today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            day_dir = self._log_dir / today
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: _write_log_files(day_dir, sandbox_id, stdout, stderr)
            )
        except Exception as exc:
            log.warning("sandbox.registry.log_write_failed", error=str(exc))

    async def cleanup_old_logs(self) -> int:
        """Remove diretórios de log mais antigos que _RETENTION_DAYS. Retorna quantos removidos."""
        import shutil
        removed = 0
        try:
            cutoff = time.time() - _RETENTION_DAYS * 86400
            for d in self._log_dir.iterdir():
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d)
                    removed += 1
        except Exception:
            pass
        return removed


def _write_log_files(day_dir: Path, sandbox_id: str, stdout: str, stderr: str) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{sandbox_id}.out").write_text(stdout, encoding="utf-8")
    (day_dir / f"{sandbox_id}.err").write_text(stderr, encoding="utf-8")
