"""
Static analysis: verifies that lora_trainer.py respects the exec_tool-only rule
for training subprocesses (Orchestrator lint check — C14 / C6).

Rules:
  - Training and merge steps MUST use exec_tool (sandboxed).
  - Direct subprocess.run / subprocess.Popen / os.system for training is FORBIDDEN.
  - Exception: _ollama_create uses subprocess.run (Ollama registration = infrastructure,
    not sandboxed code execution). This documented exception is validated below.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import pytest

import agent.finetune.lora_trainer as lora_trainer_module


def _source_of_method(cls, method_name: str) -> str:
    """Returns the source of a method, dedented."""
    method = getattr(cls, method_name)
    return textwrap.dedent(inspect.getsource(method))


# ── Exec-tool enforcement ─────────────────────────────────────────────────────

class TestOrchestratorLint:
    def test_run_training_calls_exec_tool(self):
        """_run_training must call exec_tool, not subprocess directly."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_run_training")
        assert "exec_tool" in src, "_run_training must use exec_tool for sandboxed training"
        assert "subprocess.Popen" not in src
        assert "subprocess.call" not in src

    def test_merge_and_quantize_calls_exec_tool(self):
        """_merge_and_quantize must call exec_tool, not subprocess directly."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_merge_and_quantize")
        assert "exec_tool" in src, "_merge_and_quantize must use exec_tool for sandboxed merge"
        assert "subprocess.Popen" not in src
        assert "os.system" not in src

    def test_ollama_create_uses_subprocess_run_documented_exception(self):
        """_ollama_create uses subprocess.run (documented infrastructure exception)."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_ollama_create")
        assert "subprocess.run" in src, (
            "_ollama_create should use subprocess.run — "
            "Ollama registration is infrastructure, not sandboxed execution"
        )
        assert "exec_tool" not in src, (
            "_ollama_create should NOT use exec_tool — Ollama CLI is host infrastructure"
        )

    def test_train_method_does_not_call_subprocess_directly(self):
        """The main train() method must not spawn subprocesses directly."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "train")
        # train() delegates to _run_training and _merge_and_quantize — no direct subprocess
        assert "subprocess.Popen" not in src
        assert "subprocess.call" not in src
        assert "os.system" not in src

    def test_check_gpu_uses_subprocess_run_for_nvidia_smi(self):
        """_check_gpu uses subprocess.run for nvidia-smi (read-only hardware probe)."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_check_gpu")
        assert "subprocess.run" in src
        assert "nvidia-smi" in src


# ── Policy profile name ───────────────────────────────────────────────────────

class TestPolicyProfileName:
    def test_run_training_uses_finetune_policy(self):
        """exec_tool in _run_training must specify policy_name='finetune'."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_run_training")
        assert "finetune" in src, "policy_name must be 'finetune' in _run_training"

    def test_merge_and_quantize_uses_finetune_policy(self):
        """exec_tool in _merge_and_quantize must specify policy_name='finetune'."""
        src = _source_of_method(lora_trainer_module.LoraTrainer, "_merge_and_quantize")
        assert "finetune" in src, "policy_name must be 'finetune' in _merge_and_quantize"


# ── Module-level forbidden patterns ──────────────────────────────────────────

class TestModuleForbiddenPatterns:
    def test_no_os_system_in_module(self):
        """os.system must not appear anywhere in lora_trainer.py."""
        source_path = Path(inspect.getfile(lora_trainer_module))
        source = source_path.read_text()
        # os.system is always forbidden — no documented exceptions
        assert "os.system(" not in source

    def test_no_subprocess_popen_in_module(self):
        """subprocess.Popen must not appear in lora_trainer.py."""
        source_path = Path(inspect.getfile(lora_trainer_module))
        source = source_path.read_text()
        assert "subprocess.Popen" not in source
