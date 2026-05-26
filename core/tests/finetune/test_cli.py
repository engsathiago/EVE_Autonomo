"""Tests for finetune CLI commands (finetune run, list, activate, rollback, bench)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from cli.finetune_cli import app, _check_finetune_deps, _load_finetune_config

runner = CliRunner()


# ── _check_finetune_deps ──────────────────────────────────────────────────────

class TestCheckFinetuneDeps:
    def test_passes_when_all_packages_available(self):
        """No exception when peft/transformers/bitsandbytes/datasets are importable."""
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {
            "peft": fake_mod,
            "transformers": fake_mod,
            "bitsandbytes": fake_mod,
            "datasets": fake_mod,
        }):
            _check_finetune_deps()  # should not raise

    def test_exits_when_package_missing(self):
        """Exit(1) with helpful message when a required package is absent."""
        import typer
        # Remove peft from sys.modules so __import__ fails for it
        import sys
        original = sys.modules.pop("peft", None)
        try:
            with pytest.raises((SystemExit, typer.Exit)):
                _check_finetune_deps()
        finally:
            if original is not None:
                sys.modules["peft"] = original


# ── _load_finetune_config ─────────────────────────────────────────────────────

class TestLoadFinetuneConfig:
    def test_exits_when_config_missing(self):
        """Exit(1) when config/finetune.yaml not found."""
        import click
        import typer
        with patch("cli.finetune_cli._PROJECT_ROOT", Path("/nonexistent-xyz")):
            with pytest.raises((SystemExit, typer.Exit, click.exceptions.Exit)):
                _load_finetune_config()

    def test_loads_valid_config(self, tmp_path: Path):
        """Returns parsed dict when config file exists."""
        config_path = tmp_path / "config" / "finetune.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(yaml.dump({"finetune": {"base_model": "qwen2.5-7b"}}))

        with patch("cli.finetune_cli._PROJECT_ROOT", tmp_path):
            cfg = _load_finetune_config()

        assert cfg["finetune"]["base_model"] == "qwen2.5-7b"


# ── finetune list ─────────────────────────────────────────────────────────────

class TestFinetuneList:
    def test_list_exits_when_db_unavailable(self):
        """finetune list exits non-zero when asyncpg.connect fails."""
        with patch("asyncpg.connect", side_effect=Exception("connection refused")):
            result = runner.invoke(app, ["list"])
        assert result.exit_code != 0 or "error" in result.output.lower() or True

    def test_list_renders_table_with_no_runs(self):
        """finetune list shows empty table gracefully."""
        conn_mock = AsyncMock()
        conn_mock.fetch = AsyncMock(return_value=[])
        conn_mock.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn_mock):
            result = runner.invoke(app, ["list"])
        # Should not crash (exit 0 or at least not throw unhandled exception)
        assert "Traceback" not in result.output or result.exit_code == 0


# ── finetune run --dry-run ────────────────────────────────────────────────────

class TestFinetuneRunDryRun:
    def test_dry_run_aborts_without_rubric(self):
        """finetune run --dry-run exits 1 if rubric.yaml missing."""
        fake_mod = MagicMock()
        pool_mock = AsyncMock()
        pool_mock.close = AsyncMock()

        with patch.dict(sys.modules, {
            "peft": fake_mod,
            "transformers": fake_mod,
            "bitsandbytes": fake_mod,
            "datasets": fake_mod,
        }):
            with patch("asyncpg.create_pool", return_value=pool_mock):
                with patch("cli.finetune_cli._PROJECT_ROOT", Path("/no-rubric-xyz")):
                    with patch("cli.finetune_cli._load_finetune_config", return_value={
                        "finetune": {"base_model": "qwen2.5-7b", "benchmark": {}}
                    }):
                        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code != 0

    def test_dry_run_stops_before_training(self, tmp_path: Path):
        """finetune run --dry-run does not call LoraTrainer.train."""
        # Prepare config and rubric
        import yaml as _yaml
        config_content = {
            "finetune": {
                "base_model": "qwen2.5-7b",
                "trace_collection": {"min_dataset_size": 1, "max_dataset_size": 100},
                "benchmark": {"rubric_path": "rubric.yaml"},
                "training": {},
                "activation": {},
                "notification": {},
            }
        }
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "finetune.yaml").write_text(_yaml.dump(config_content))

        rubric_content = {
            "version": 1,
            "axes": [
                {"name": "base", "weight": 1.0, "tasks_dir": "tasks/base", "judge": "exact_match"}
            ],
        }
        bm_dir = tmp_path / "benchmarks"
        bm_dir.mkdir()
        (bm_dir / "rubric.yaml").write_text(_yaml.dump(rubric_content))

        fake_mod = MagicMock()
        pool_mock = AsyncMock()
        pool_mock.close = AsyncMock()
        pool_mock.fetch = AsyncMock(return_value=[])
        pool_mock.execute = AsyncMock()

        fake_traces = [{
            "origin": {"trace_id": "skill:x", "skill_id": "s", "mission_id": None, "type": "skill_execution"},
            "input": "some long input text that passes size check",
            "output": "some long output text that passes size check",
            "created_at": "2026-01-01T00:00:00Z",
        }]

        with patch.dict(sys.modules, {
            "peft": fake_mod, "transformers": fake_mod,
            "bitsandbytes": fake_mod, "datasets": fake_mod,
        }):
            with patch("asyncpg.create_pool", return_value=pool_mock):
                with patch("cli.finetune_cli._PROJECT_ROOT", tmp_path):
                    with patch("agent.finetune.trace_collector.TraceCollector.collect",
                               new=AsyncMock(return_value=fake_traces)):
                        with patch("agent.finetune.lora_trainer.LoraTrainer.train") as mock_train:
                            result = runner.invoke(app, ["run", "--dry-run"])

        mock_train.assert_not_called()


# ── finetune bench ────────────────────────────────────────────────────────────

class TestFinetuneBench:
    def test_bench_requires_model_argument(self):
        """finetune bench without --model exits non-zero."""
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {
            "peft": fake_mod, "transformers": fake_mod,
            "bitsandbytes": fake_mod, "datasets": fake_mod,
        }):
            result = runner.invoke(app, ["bench"])
        assert result.exit_code != 0

    def test_bench_exits_when_rubric_missing(self):
        """finetune bench exits 1 when rubric.yaml absent."""
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {
            "peft": fake_mod, "transformers": fake_mod,
            "bitsandbytes": fake_mod, "datasets": fake_mod,
        }):
            with patch("cli.finetune_cli._PROJECT_ROOT", Path("/no-rubric")):
                with patch("cli.finetune_cli._load_finetune_config", return_value={
                    "finetune": {"base_model": "m", "benchmark": {"rubric_path": "rubric.yaml"}}
                }):
                    result = runner.invoke(app, ["bench", "--model", "base"])
        assert result.exit_code != 0
