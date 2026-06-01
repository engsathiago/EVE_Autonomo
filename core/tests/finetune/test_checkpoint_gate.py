"""Tests for checkpoint_gate.py — C8, C9 (gate decision logic)."""
from __future__ import annotations

from agent.finetune.checkpoint_gate import CheckpointGate
from agent.finetune.rubric import Rubric, RubricAxis, RubricThresholds
from agent.finetune.safety_check import SafetyResult


def _make_rubric(regression_intolerant_axes: list[str] | None = None) -> Rubric:
    axes = [
        RubricAxis("base_capabilities", 0.25, "t", "exact_match",
                   regression_intolerant=("base_capabilities" in (regression_intolerant_axes or []))),
        RubricAxis("safety", 0.10, "t", "refusal_check",
                   regression_intolerant=("safety" in (regression_intolerant_axes or []))),
        RubricAxis("summarization", 0.20, "t", "rouge_l_plus_llm"),
        RubricAxis("classification", 0.15, "t", "exact_match"),
        RubricAxis("tier_selection", 0.15, "t", "exact_match"),
        RubricAxis("instruction", 0.15, "t", "llm_judge_claude"),
    ]
    return Rubric(version=1, axes=axes, thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0))


def _safety_ok() -> SafetyResult:
    return SafetyResult(passed=True, regressions=[], total_tasks=10, base_refusals=10, candidate_refusals=10)


def _safety_fail() -> SafetyResult:
    return SafetyResult(passed=False, regressions=[{"task_id": "safe_001", "prompt_preview": "bad", "base_refused": True, "candidate_refused": False, "candidate_output_preview": "sure"}], total_tasks=10, base_refusals=10, candidate_refusals=9)


class TestCheckpointGate:
    def _base_scores(self) -> dict[str, float]:
        return {ax: 0.80 for ax in ["base_capabilities", "safety", "summarization", "classification", "tier_selection", "instruction"]}

    def _candidate_above(self) -> dict[str, float]:
        """Candidate +5% above base — should pass all gates."""
        return {ax: 0.85 for ax in ["base_capabilities", "safety", "summarization", "classification", "tier_selection", "instruction"]}

    def _candidate_below(self) -> dict[str, float]:
        """Candidate slightly below base — should fail improvement gate."""
        return {ax: 0.79 for ax in ["base_capabilities", "safety", "summarization", "classification", "tier_selection", "instruction"]}

    def test_accepts_when_all_gates_pass(self):
        """C8: accepted when score > base+3% and no regression and safety ok."""
        rubric = _make_rubric(["base_capabilities", "safety"])
        gate = CheckpointGate(rubric=rubric)
        decision = gate.decide(self._base_scores(), self._candidate_above(), _safety_ok())
        assert decision.accepted is True
        assert decision.reason == "all_gates_passed"

    def test_rejects_on_safety_failure(self):
        """C8: SAFETY_REGRESSION reason when candidate fails safety."""
        rubric = _make_rubric(["safety"])
        gate = CheckpointGate(rubric=rubric, safety_strict=True)
        decision = gate.decide(self._base_scores(), self._candidate_above(), _safety_fail())
        assert decision.accepted is False
        assert "SAFETY_REGRESSION" in decision.reason

    def test_rejects_on_insufficient_improvement(self):
        """C8: INSUFFICIENT_IMPROVEMENT when delta < min_improvement_pct."""
        rubric = _make_rubric()
        gate = CheckpointGate(rubric=rubric)
        decision = gate.decide(self._base_scores(), self._candidate_below(), _safety_ok())
        assert decision.accepted is False
        assert "INSUFFICIENT_IMPROVEMENT" in decision.reason

    def test_rejects_on_axis_regression_beyond_threshold(self):
        """C8: REGRESSION_AXIS when any axis drops > max_regression_pct."""
        rubric = _make_rubric()
        gate = CheckpointGate(rubric=rubric)
        base = self._base_scores()
        cand = self._candidate_above()
        cand["summarization"] = 0.70  # dropped 10% — exceeds 5% threshold
        decision = gate.decide(base, cand, _safety_ok())
        assert decision.accepted is False
        assert "REGRESSION_AXIS_SUMMARIZATION" in decision.reason

    def test_rejects_on_regression_intolerant_axis_small_drop(self):
        """C8: regression_intolerant axis rejects at >1% drop even if others are fine."""
        rubric = _make_rubric(["base_capabilities"])
        gate = CheckpointGate(rubric=rubric)
        base = self._base_scores()
        cand = self._candidate_above()
        cand["base_capabilities"] = 0.785  # 1.5% drop on intolerant axis
        decision = gate.decide(base, cand, _safety_ok())
        assert decision.accepted is False
        assert "REGRESSION_INTOLERANT_AXIS_BASE_CAPABILITIES" in decision.reason

    def test_details_contain_all_axis_deltas(self):
        """Gate decision details include per-axis deltas."""
        rubric = _make_rubric()
        gate = CheckpointGate(rubric=rubric)
        decision = gate.decide(self._base_scores(), self._candidate_above(), _safety_ok())
        assert "axis_deltas" in decision.details
        assert len(decision.details["axis_deltas"]) == 6

    def test_non_strict_safety_does_not_reject_on_failure(self):
        """safety_strict=False: safety failure is not a gate."""
        rubric = _make_rubric()
        gate = CheckpointGate(rubric=rubric, safety_strict=False)
        decision = gate.decide(self._base_scores(), self._candidate_above(), _safety_fail())
        # Without safety strict, might still pass other gates
        # (safety regressions not counted as rejection cause)
        assert "SAFETY_REGRESSION" not in decision.reason
