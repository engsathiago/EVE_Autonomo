"""Tests for finetune exceptions."""

from __future__ import annotations

from agent.finetune.exceptions import (
    AutoActivateNotAllowed,
    BenchmarkError,
    DatasetTooSmall,
    FinetuneError,
    GateRejected,
)


def test_finetune_error_is_runtime_error():
    exc = FinetuneError("base error")
    assert isinstance(exc, RuntimeError)


def test_benchmark_error_message():
    exc = BenchmarkError("rubric ausente")
    assert "rubric" in str(exc).lower()
    assert isinstance(exc, FinetuneError)


def test_gate_rejected_stores_reason_and_details():
    exc = GateRejected("SAFETY_REGRESSION", details={"regressions": 2})
    assert exc.reason == "SAFETY_REGRESSION"
    assert exc.details["regressions"] == 2


def test_dataset_too_small_message_contains_numbers():
    exc = DatasetTooSmall(found=42, required=100)
    assert "42" in str(exc)
    assert "100" in str(exc)
    assert exc.found == 42
    assert exc.required == 100


def test_auto_activate_not_allowed_message():
    exc = AutoActivateNotAllowed(accepted=3, required=5)
    assert "3" in str(exc)
    assert "5" in str(exc)
    assert exc.accepted == 3
    assert exc.required == 5
