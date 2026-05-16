"""Tests for reports.py — C12 (markdown generation)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.finetune.reports import generate_report
from agent.finetune.safety_check import SafetyResult


def _make_gate_decision(accepted: bool, reason: str = "all_gates_passed") -> MagicMock:
    d = MagicMock()
    d.accepted = accepted
    d.reason = reason
    d.details = {
        "base_weighted": 0.80,
        "candidate_weighted": 0.84,
        "overall_delta_pct": 4.0,
        "axis_deltas": {"base_capabilities": 5.0, "safety": 3.0},
    }
    return d


def _make_safety_result(passed: bool = True) -> SafetyResult:
    return SafetyResult(
        passed=passed,
        regressions=[],
        total_tasks=12,
        base_refusals=12,
        candidate_refusals=12,
    )


class TestGenerateReport:
    def test_creates_markdown_file(self, tmp_path: Path):
        """C12: gera arquivo markdown."""
        output = tmp_path / "report.md"
        report = generate_report(
            run_id="run-abc123",
            checkpoint_id="ckpt-20260516-abc123",
            base_model="qwen2.5-7b",
            base_scores={"base_capabilities": 0.80, "safety": 0.90},
            candidate_scores={"base_capabilities": 0.85, "safety": 0.92},
            gate_decision=_make_gate_decision(True),
            safety_result=_make_safety_result(),
            dataset_size=500,
            config={"lora_r": 16, "epochs": 2},
            output_path=output,
        )
        assert output.exists()
        assert len(report) > 100

    def test_report_contains_run_id(self, tmp_path: Path):
        output = tmp_path / "report.md"
        report = generate_report(
            run_id="run-unique-id",
            checkpoint_id="ckpt-1",
            base_model="qwen2.5-7b",
            base_scores={"base": 0.80},
            candidate_scores={"base": 0.85},
            gate_decision=_make_gate_decision(True),
            safety_result=_make_safety_result(),
            dataset_size=100,
            config={},
            output_path=output,
        )
        assert "run-unique-id" in report

    def test_report_shows_rejected_status(self, tmp_path: Path):
        output = tmp_path / "report.md"
        report = generate_report(
            run_id="run-1",
            checkpoint_id=None,
            base_model="qwen2.5-7b",
            base_scores={"base": 0.80},
            candidate_scores={"base": 0.75},
            gate_decision=_make_gate_decision(False, reason="INSUFFICIENT_IMPROVEMENT"),
            safety_result=_make_safety_result(),
            dataset_size=100,
            config={},
            output_path=output,
        )
        assert "REJECTED" in report
        assert "INSUFFICIENT_IMPROVEMENT" in report

    def test_report_shows_delta_scores(self, tmp_path: Path):
        output = tmp_path / "report.md"
        report = generate_report(
            run_id="run-1",
            checkpoint_id="ckpt-1",
            base_model="qwen2.5-7b",
            base_scores={"base_capabilities": 0.80},
            candidate_scores={"base_capabilities": 0.85},
            gate_decision=_make_gate_decision(True),
            safety_result=_make_safety_result(),
            dataset_size=200,
            config={"lora_r": 16},
            output_path=output,
        )
        assert "base_capabilities" in report
        assert "0.800" in report or "0.80" in report
        assert "0.850" in report or "0.85" in report

    def test_report_contains_hyperparameters(self, tmp_path: Path):
        output = tmp_path / "report.md"
        report = generate_report(
            run_id="run-1",
            checkpoint_id="ckpt-1",
            base_model="qwen2.5-7b",
            base_scores={},
            candidate_scores={},
            gate_decision=_make_gate_decision(True),
            safety_result=_make_safety_result(),
            dataset_size=100,
            config={"lora_r": 16, "epochs": 2, "batch_size": 4},
            output_path=output,
        )
        assert "lora_r" in report
        assert "epochs" in report
