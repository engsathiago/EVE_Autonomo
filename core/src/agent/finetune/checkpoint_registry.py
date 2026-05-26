"""
CRUD operations for finetune_runs and finetune_checkpoints.

Activation is atomic: writes active_checkpoint.txt via tempfile + os.replace.
Never opens the destination file directly for writing.
Auto-activation requires explicit human acceptance history before enabling.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.finetune.exceptions import (
    AutoActivateNotAllowed,
    CheckpointActivationError,
)
from agent.observability.logger import get_logger

log = get_logger(__name__)


class CheckpointRegistry:
    def __init__(
        self,
        pool: Any,  # asyncpg pool
        models_dir: Path,
        auto_activate: bool = False,
        auto_activate_after_n_accepted: int = 5,
    ) -> None:
        self._pool = pool
        self._models_dir = models_dir
        self._auto_activate = auto_activate
        self._auto_n = auto_activate_after_n_accepted
        self._active_checkpoint_file = models_dir / "active_checkpoint.txt"

    # ── Run CRUD ──────────────────────────────────────────────────────────────

    async def create_run(
        self,
        run_id: str,
        base_model: str,
        dataset_path: Path,
        dataset_size: int,
        config: dict[str, Any],
        triggered_by: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        await self._pool.execute(
            """
            INSERT INTO finetune_runs
                (id, started_at, status, base_model, dataset_path, dataset_size, config, triggered_by)
            VALUES ($1, $2, 'running', $3, $4, $5, $6, $7)
            """,
            run_id,
            now,
            base_model,
            str(dataset_path),
            dataset_size,
            json.dumps(config),
            triggered_by,
        )

    async def finish_run(
        self,
        run_id: str,
        status: str,
        checkpoint_id: str | None = None,
        benchmark_score: dict[str, Any] | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        await self._pool.execute(
            """
            UPDATE finetune_runs
            SET finished_at=$1, status=$2, checkpoint_id=$3,
                benchmark_score=$4, rejection_reason=$5
            WHERE id=$6
            """,
            now,
            status,
            checkpoint_id,
            json.dumps(benchmark_score) if benchmark_score else None,
            rejection_reason,
            run_id,
        )

    # ── Checkpoint CRUD ───────────────────────────────────────────────────────

    async def create_checkpoint(
        self,
        checkpoint_id: str,
        run_id: str,
        base_model: str,
        path: Path,
        benchmark_score: dict[str, Any],
    ) -> None:
        now = datetime.now(tz=UTC)
        await self._pool.execute(
            """
            INSERT INTO finetune_checkpoints
                (id, run_id, base_model, path, created_at, benchmark_score, state)
            VALUES ($1, $2, $3, $4, $5, $6, 'candidate')
            """,
            checkpoint_id,
            run_id,
            base_model,
            str(path),
            now,
            json.dumps(benchmark_score),
        )

    async def reject_checkpoint(self, checkpoint_id: str) -> None:
        await self._pool.execute(
            "UPDATE finetune_checkpoints SET state='rejected' WHERE id=$1",
            checkpoint_id,
        )

    async def activate(self, checkpoint_id: str, *, auto: bool = False) -> None:
        """
        Marks checkpoint as active and writes active_checkpoint.txt atomically.

        If auto=True, validates that enough human-accepted runs exist first.
        Raises AutoActivateNotAllowed or CheckpointActivationError on failure.
        """
        if auto:
            accepted = await self._count_human_accepted_runs()
            if accepted < self._auto_n:
                raise AutoActivateNotAllowed(accepted=accepted, required=self._auto_n)

        row = await self._pool.fetchrow(
            "SELECT id, path FROM finetune_checkpoints WHERE id=$1", checkpoint_id
        )
        if row is None:
            raise CheckpointActivationError(
                f"Checkpoint '{checkpoint_id}' não encontrado no banco."
            )

        now = datetime.now(tz=UTC)

        # Deactivate previous active checkpoint
        prev = await self._pool.fetchrow(
            "SELECT id FROM finetune_checkpoints WHERE state='active' LIMIT 1"
        )
        if prev:
            await self._pool.execute(
                "UPDATE finetune_checkpoints SET state='archived', deactivated_at=$1 WHERE id=$2",
                now,
                prev["id"],
            )

        # Activate new
        await self._pool.execute(
            "UPDATE finetune_checkpoints SET state='active', activated_at=$1 WHERE id=$2",
            now,
            checkpoint_id,
        )

        # Atomic write of active_checkpoint.txt
        self._atomic_write_active(checkpoint_id)

        log.info(
            "checkpoint_registry.activated",
            checkpoint_id=checkpoint_id,
            previous=prev["id"] if prev else "base",
            auto=auto,
        )

    async def rollback(self) -> str:
        """
        Rolls back to the previous active checkpoint (or 'base' if none).
        Returns the ID we rolled back to.
        """
        current = await self._pool.fetchrow(
            "SELECT id FROM finetune_checkpoints WHERE state='active' LIMIT 1"
        )
        if current:
            await self._pool.execute(
                "UPDATE finetune_checkpoints SET state='archived', deactivated_at=$1 WHERE id=$2",
                datetime.now(tz=UTC),
                current["id"],
            )

        # Find last archived (previously active)
        prev = await self._pool.fetchrow(
            """
            SELECT id FROM finetune_checkpoints
            WHERE state='archived' AND deactivated_at IS NOT NULL
            ORDER BY deactivated_at DESC
            LIMIT 1
            """
        )
        if prev:
            target_id = prev["id"]
            await self._pool.execute(
                "UPDATE finetune_checkpoints SET state='active', activated_at=$1 WHERE id=$2",
                datetime.now(tz=UTC),
                target_id,
            )
            self._atomic_write_active(target_id)
        else:
            target_id = "base"
            self._atomic_write_active("base")

        log.info(
            "checkpoint_registry.rolled_back",
            from_id=current["id"] if current else "none",
            to_id=target_id,
        )
        return target_id

    async def list_checkpoints(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT c.id, c.run_id, c.base_model, c.path, c.created_at,
                   c.benchmark_score, c.state, c.activated_at, c.deactivated_at,
                   r.triggered_by, r.dataset_size
            FROM finetune_checkpoints c
            JOIN finetune_runs r ON r.id = c.run_id
            ORDER BY c.created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT id, started_at, finished_at, status, base_model,
                   checkpoint_id, dataset_size, benchmark_score,
                   rejection_reason, triggered_by
            FROM finetune_runs
            ORDER BY started_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    def get_active_checkpoint(self) -> str:
        """Returns the current active checkpoint ID, or 'base'."""
        if self._active_checkpoint_file.exists():
            return self._active_checkpoint_file.read_text().strip() or "base"
        return "base"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _atomic_write_active(self, checkpoint_id: str) -> None:
        """Writes active_checkpoint.txt atomically via tempfile + os.replace."""
        self._active_checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._active_checkpoint_file.parent),
                prefix=".active_checkpoint_tmp_",
            )
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(checkpoint_id)
            except Exception:
                os.unlink(tmp_path)
                raise
            os.replace(tmp_path, str(self._active_checkpoint_file))
        except OSError as exc:
            raise CheckpointActivationError(
                f"Falha ao escrever active_checkpoint.txt atomicamente: {exc}"
            ) from exc

    async def _count_human_accepted_runs(self) -> int:
        """Counts runs accepted by human activation (not auto)."""
        row = await self._pool.fetchrow(
            """
            SELECT COUNT(*) AS n FROM finetune_checkpoints
            WHERE state IN ('active','archived')
            """
        )
        return int(row["n"]) if row else 0

    async def can_auto_activate(self) -> bool:
        if not self._auto_activate:
            return False
        accepted = await self._count_human_accepted_runs()
        return accepted >= self._auto_n
