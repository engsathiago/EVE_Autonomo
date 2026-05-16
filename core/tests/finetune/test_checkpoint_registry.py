"""Tests for checkpoint_registry.py — C9, C10, C11 (activation/rollback)."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.finetune.checkpoint_registry import CheckpointRegistry
from agent.finetune.exceptions import AutoActivateNotAllowed, CheckpointActivationError


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path: Path):
        """C10: active_checkpoint.txt criado atomicamente."""
        registry = CheckpointRegistry(pool=MagicMock(), models_dir=tmp_path)
        registry._atomic_write_active("test-ckpt-123")
        active_file = tmp_path / "active_checkpoint.txt"
        assert active_file.exists()
        assert active_file.read_text() == "test-ckpt-123"

    def test_atomic_write_updates_existing(self, tmp_path: Path):
        """C10: atualização atômica sobrescreve corretamente."""
        registry = CheckpointRegistry(pool=MagicMock(), models_dir=tmp_path)
        registry._atomic_write_active("ckpt-v1")
        registry._atomic_write_active("ckpt-v2")
        assert (tmp_path / "active_checkpoint.txt").read_text() == "ckpt-v2"

    def test_get_active_returns_base_when_no_file(self, tmp_path: Path):
        registry = CheckpointRegistry(pool=MagicMock(), models_dir=tmp_path)
        assert registry.get_active_checkpoint() == "base"

    def test_get_active_returns_content(self, tmp_path: Path):
        registry = CheckpointRegistry(pool=MagicMock(), models_dir=tmp_path)
        registry._atomic_write_active("my-checkpoint")
        assert registry.get_active_checkpoint() == "my-checkpoint"


class TestAutoActivation:
    @pytest.mark.asyncio
    async def test_raises_when_auto_activate_before_n_accepted(self, tmp_path: Path):
        """C9: AutoActivateNotAllowed quando accepted_runs < auto_activate_after_n_accepted."""
        pool = AsyncMock()
        pool.fetchrow.return_value = {"id": "ckpt-1", "path": str(tmp_path)}
        pool.execute = AsyncMock()
        # _count_human_accepted_runs returns 2 (below threshold of 5)
        pool.fetchrow.side_effect = [
            {"id": "ckpt-1", "path": str(tmp_path)},  # first fetch (checkpoint lookup)
            None,  # no previous active
            {"n": 2},  # accepted count
        ]

        registry = CheckpointRegistry(
            pool=pool,
            models_dir=tmp_path,
            auto_activate=True,
            auto_activate_after_n_accepted=5,
        )

        # Override _count_human_accepted_runs directly
        async def _low_count() -> int:
            return 2

        registry._count_human_accepted_runs = _low_count  # type: ignore[method-assign]

        with pytest.raises(AutoActivateNotAllowed) as exc_info:
            await registry.activate("ckpt-1", auto=True)
        assert exc_info.value.accepted == 2
        assert exc_info.value.required == 5

    @pytest.mark.asyncio
    async def test_can_auto_activate_false_when_disabled(self, tmp_path: Path):
        registry = CheckpointRegistry(
            pool=AsyncMock(),
            models_dir=tmp_path,
            auto_activate=False,
        )
        result = await registry.can_auto_activate()
        assert result is False


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_create_run_calls_execute(self, tmp_path: Path):
        pool = AsyncMock()
        pool.execute = AsyncMock()
        registry = CheckpointRegistry(pool=pool, models_dir=tmp_path)
        await registry.create_run(
            run_id="run-001",
            base_model="qwen2.5-7b",
            dataset_path=Path("datasets/test.jsonl"),
            dataset_size=500,
            config={"lora_r": 16},
            triggered_by="cli",
        )
        pool.execute.assert_called_once()
        call_args = pool.execute.call_args[0]
        assert "INSERT INTO finetune_runs" in call_args[0]
        assert call_args[1] == "run-001"

    @pytest.mark.asyncio
    async def test_finish_run_updates_status(self, tmp_path: Path):
        pool = AsyncMock()
        pool.execute = AsyncMock()
        registry = CheckpointRegistry(pool=pool, models_dir=tmp_path)
        await registry.finish_run(run_id="run-001", status="accepted", checkpoint_id="ckpt-1")
        pool.execute.assert_called_once()
        call_args = pool.execute.call_args[0]
        assert "UPDATE finetune_runs" in call_args[0]
        assert "accepted" in call_args
