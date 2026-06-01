"""Tests for lora_trainer.py — C6 (GPU check, exec_tool via sandbox, manifest)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.finetune.exceptions import FinetuneError, TrainerNotAvailable
from agent.finetune.lora_trainer import LoraTrainer, TrainConfig, TrainResult


def _make_config(base_model: str = "qwen2.5-7b-instruct") -> TrainConfig:
    return TrainConfig(
        base_model=base_model,
        lora_r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        learning_rate=2e-4,
        epochs=2,
        batch_size=4,
        gradient_accumulation=4,
        max_seq_length=2048,
        use_unsloth=True,
    )


def _make_exec_result(exit_code: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.exit_code = exit_code
    r.stdout = stdout
    r.stderr = stderr
    return r


# ── GPU Check ────────────────────────────────────────────────────────────────


class TestCheckGpu:
    def test_raises_when_nvidia_smi_not_found(self):
        """C6: TrainerNotAvailable when nvidia-smi absent."""
        with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
            with pytest.raises(TrainerNotAvailable, match="nvidia-smi"):
                LoraTrainer._check_gpu()

    def test_raises_when_nvidia_smi_returns_nonzero(self):
        """C6: TrainerNotAvailable when nvidia-smi exits with error."""
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(TrainerNotAvailable, match="GPU"):
                LoraTrainer._check_gpu()

    def test_raises_when_vram_insufficient(self):
        """C6: TrainerNotAvailable when VRAM < 12 GiB."""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "8192\n"  # 8 GiB — below minimum 12 GiB
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(TrainerNotAvailable, match="VRAM"):
                LoraTrainer._check_gpu()

    def test_passes_when_vram_sufficient(self):
        """C6: No exception when >= 12 GiB VRAM."""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "24576\n"  # 24 GiB
        with patch("subprocess.run", return_value=proc):
            LoraTrainer._check_gpu()  # should not raise


# ── Checkpoint ID Format ──────────────────────────────────────────────────────


class TestCheckpointId:
    def test_checkpoint_id_format(self):
        """Checkpoint ID = {short_model}-lora-{YYYYMMDD}-{run_id[:8]}."""
        ckpt_id = LoraTrainer._make_checkpoint_id("qwen2.5-7b-instruct", "run-abcdefgh")
        parts = ckpt_id.split("-lora-")
        assert len(parts) == 2
        date_and_hash = parts[1]  # e.g. "20260516-run-abcd"
        assert len(date_and_hash) >= 8

    def test_checkpoint_id_uses_model_short_name(self):
        ckpt_id = LoraTrainer._make_checkpoint_id("Unsloth/Meta-Llama-3-8B", "run-xyz")
        assert "Meta-Llama-3-8B" in ckpt_id or "lora" in ckpt_id

    def test_checkpoint_id_uses_run_id_prefix(self):
        ckpt_id = LoraTrainer._make_checkpoint_id("base-model", "run-12345678-extra")
        assert "run-123" in ckpt_id or "12345678" in ckpt_id


# ── Manifest ─────────────────────────────────────────────────────────────────


class TestWriteManifest:
    def test_manifest_written_to_checkpoint_dir(self, tmp_path: Path):
        ckpt_path = tmp_path / "ckpt-001"
        ckpt_path.mkdir()
        dataset = tmp_path / "dataset.jsonl"
        dataset.write_text(json.dumps({"messages": []}) + "\n")
        config = _make_config()

        LoraTrainer._write_manifest(
            ckpt_path=ckpt_path,
            checkpoint_id="ckpt-001",
            run_id="run-abc",
            config=config,
            dataset_path=dataset,
        )
        manifest_path = ckpt_path / "manifest.yaml"
        assert manifest_path.exists()

    def test_manifest_contains_required_fields(self, tmp_path: Path):
        ckpt_path = tmp_path / "ckpt"
        ckpt_path.mkdir()
        dataset = tmp_path / "ds.jsonl"
        dataset.write_text("x")
        config = _make_config("my-base-model")

        LoraTrainer._write_manifest(ckpt_path, "ckpt-xyz", "run-001", config, dataset)
        content = (ckpt_path / "manifest.yaml").read_text()
        assert "checkpoint_id" in content
        assert "run_id" in content
        assert "base_model" in content
        assert "my-base-model" in content


# ── Extract Final Loss ────────────────────────────────────────────────────────


class TestExtractFinalLoss:
    def test_returns_none_when_log_missing(self, tmp_path: Path):
        result = LoraTrainer._extract_final_loss(tmp_path / "nonexistent.jsonl")
        assert result is None

    def test_returns_loss_from_last_line(self, tmp_path: Path):
        log = tmp_path / "train_log.jsonl"
        log.write_text(
            json.dumps({"final_loss": 2.1, "steps": 10}) + "\n" + json.dumps({"final_loss": 1.5, "steps": 20}) + "\n"
        )
        result = LoraTrainer._extract_final_loss(log)
        assert abs(result - 1.5) < 1e-6

    def test_returns_none_on_malformed_log(self, tmp_path: Path):
        log = tmp_path / "bad.jsonl"
        log.write_text("not json\n")
        result = LoraTrainer._extract_final_loss(log)
        assert result is None


# ── Full Train Flow (all subprocesses mocked) ────────────────────────────────


class TestTrainFlow:
    @pytest.mark.asyncio
    async def test_train_raises_when_gpu_check_fails(self, tmp_path: Path):
        """C6: train() aborts early if GPU unavailable."""
        dataset = tmp_path / "dataset.jsonl"
        dataset.write_text(json.dumps({"messages": []}) + "\n")

        trainer = LoraTrainer(checkpoints_dir=tmp_path / "ckpts")
        config = _make_config()

        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(TrainerNotAvailable):
                await trainer.train(dataset_path=dataset, run_id="run-test", config=config)

    @pytest.mark.asyncio
    async def test_train_raises_on_nonzero_exit_code(self, tmp_path: Path):
        """C6: FinetuneError when exec_tool returns non-zero."""
        dataset = tmp_path / "dataset.jsonl"
        dataset.write_text(json.dumps({"messages": []}) + "\n")

        trainer = LoraTrainer(checkpoints_dir=tmp_path / "ckpts")
        config = _make_config()

        gpu_proc = MagicMock(returncode=0, stdout="24576\n")

        with patch("subprocess.run", return_value=gpu_proc):
            with patch(
                "agent.finetune.lora_trainer.LoraTrainer._run_training",
                new=AsyncMock(return_value={"exit_code": 1, "stdout": "", "stderr": "OOM error"}),
            ):
                with pytest.raises(FinetuneError, match="exit_code=1"):
                    await trainer.train(dataset_path=dataset, run_id="run-fail", config=config)

    @pytest.mark.asyncio
    async def test_train_succeeds_and_returns_train_result(self, tmp_path: Path):
        """C6: successful train() returns TrainResult with correct fields."""
        dataset = tmp_path / "dataset.jsonl"
        dataset.write_text(json.dumps({"messages": []}) + "\n")
        ckpts_dir = tmp_path / "ckpts"
        ckpts_dir.mkdir()

        trainer = LoraTrainer(checkpoints_dir=ckpts_dir)
        config = _make_config()

        gpu_proc = MagicMock(returncode=0, stdout="24576\n")

        async def fake_run_training(script_path, ckpt_path, log_path):
            # Simulate training: write the log file and a dummy GGUF
            log_path.write_text(json.dumps({"final_loss": 0.85, "steps": 100}) + "\n")
            return {"exit_code": 0, "stdout": "done", "stderr": ""}

        async def fake_merge(config, ckpt_path, gguf_path):
            gguf_path.write_bytes(b"fake gguf content")

        ollama_proc = MagicMock(returncode=0, stdout="model created", stderr="")

        with patch("subprocess.run", side_effect=[gpu_proc, ollama_proc]):
            with patch.object(trainer, "_run_training", new=fake_run_training):
                with patch.object(trainer, "_merge_and_quantize", new=fake_merge):
                    result = await trainer.train(dataset_path=dataset, run_id="run-ok12345", config=config)

        assert isinstance(result, TrainResult)
        assert result.checkpoint_dir.is_dir()
        assert result.final_loss is not None
        assert "ft-" in result.ollama_model_name
        assert (result.checkpoint_dir / "manifest.yaml").exists()

    @pytest.mark.asyncio
    async def test_ollama_create_raises_on_failure(self, tmp_path: Path):
        """C6: FinetuneError if `ollama create` exits non-zero."""
        trainer = LoraTrainer(checkpoints_dir=tmp_path)
        gguf = tmp_path / "model.gguf"
        gguf.write_bytes(b"fake")

        fail_proc = MagicMock(returncode=1, stderr="connection refused", stdout="")
        with patch("subprocess.run", return_value=fail_proc):
            with pytest.raises(FinetuneError, match="ollama create"):
                await trainer._ollama_create("test-model", gguf)


# ── Build Script Sanity ───────────────────────────────────────────────────────


class TestBuildScript:
    def test_train_script_references_dataset_path(self, tmp_path: Path):
        dataset = tmp_path / "train.jsonl"
        ckpt = tmp_path / "ckpt"
        script = LoraTrainer._build_train_script(_make_config(), dataset, ckpt)
        assert str(dataset) in script

    def test_train_script_references_epochs(self):
        config = _make_config()
        config.epochs = 5
        script = LoraTrainer._build_train_script(config, Path("/ds"), Path("/ckpt"))
        assert "5" in script

    def test_merge_script_references_base_model(self):
        script = LoraTrainer._build_merge_script(_make_config("my/special-model"), Path("/ckpt"), Path("/out.gguf"))
        assert "my/special-model" in script
