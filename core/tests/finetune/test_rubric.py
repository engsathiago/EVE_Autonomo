"""Tests for rubric.py — C1 (BenchmarkError on missing/malformed rubric.yaml)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent.finetune.exceptions import BenchmarkError
from agent.finetune.rubric import Rubric, load_task_jsonl


def _write_rubric(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "rubric.yaml"
    p.write_text(yaml.dump(content))
    return p


class TestRubricLoad:
    def test_raises_benchmark_error_when_file_missing(self, tmp_path: Path):
        """C1: BenchmarkError se rubric.yaml não existe."""
        with pytest.raises(BenchmarkError, match="não encontrada"):
            Rubric.load(tmp_path / "rubric.yaml")

    def test_raises_benchmark_error_when_malformed_yaml(self, tmp_path: Path):
        """C1: BenchmarkError se YAML inválido."""
        p = tmp_path / "rubric.yaml"
        p.write_text(":\ninvalid: [unclosed")
        with pytest.raises(BenchmarkError, match="malformado"):
            Rubric.load(p)

    def test_raises_benchmark_error_when_axes_empty(self, tmp_path: Path):
        p = _write_rubric(tmp_path, {"version": 1, "axes": []})
        with pytest.raises(BenchmarkError, match="não-vazia"):
            Rubric.load(p)

    def test_raises_benchmark_error_when_weights_dont_sum_to_one(self, tmp_path: Path):
        p = _write_rubric(
            tmp_path,
            {
                "version": 1,
                "axes": [
                    {"name": "a", "weight": 0.5, "tasks_dir": "t", "judge": "exact_match"},
                    {"name": "b", "weight": 0.3, "tasks_dir": "t", "judge": "exact_match"},
                ],
            },
        )
        with pytest.raises(BenchmarkError, match="Pesos"):
            Rubric.load(p)

    def test_raises_benchmark_error_when_invalid_judge(self, tmp_path: Path):
        p = _write_rubric(
            tmp_path,
            {
                "version": 1,
                "axes": [
                    {"name": "a", "weight": 1.0, "tasks_dir": "t", "judge": "invalid_judge"},
                ],
            },
        )
        with pytest.raises(BenchmarkError, match="judge"):
            Rubric.load(p)

    def test_loads_valid_rubric(self, tmp_path: Path):
        p = _write_rubric(
            tmp_path,
            {
                "version": 1,
                "axes": [
                    {"name": "base", "weight": 0.6, "tasks_dir": "tasks/base", "judge": "exact_match"},
                    {"name": "safety", "weight": 0.4, "tasks_dir": "tasks/safety", "judge": "refusal_check"},
                ],
                "thresholds": {"min_improvement_pct": 3.0, "max_regression_pct": 5.0},
            },
        )
        rubric = Rubric.load(p)
        assert rubric.version == 1
        assert len(rubric.axes) == 2
        assert rubric.thresholds.min_improvement_pct == 3.0

    def test_weighted_score_calculation(self, tmp_path: Path):
        p = _write_rubric(
            tmp_path,
            {
                "version": 1,
                "axes": [
                    {"name": "a", "weight": 0.7, "tasks_dir": "t", "judge": "exact_match"},
                    {"name": "b", "weight": 0.3, "tasks_dir": "t", "judge": "exact_match"},
                ],
            },
        )
        rubric = Rubric.load(p)
        score = rubric.weighted_score({"a": 1.0, "b": 0.0})
        assert abs(score - 0.7) < 1e-6


class TestLoadTaskJsonl:
    def test_raises_when_file_missing(self, tmp_path: Path):
        with pytest.raises(BenchmarkError, match="não encontrado"):
            load_task_jsonl(tmp_path / "tasks.jsonl")

    def test_raises_on_invalid_json(self, tmp_path: Path):
        p = tmp_path / "tasks.jsonl"
        p.write_text("not-json\n")
        with pytest.raises(BenchmarkError, match="JSON inválido"):
            load_task_jsonl(p)

    def test_raises_when_missing_required_fields(self, tmp_path: Path):
        p = tmp_path / "tasks.jsonl"
        p.write_text(json.dumps({"id": "t1", "prompt": "p"}) + "\n")  # no expected
        with pytest.raises(BenchmarkError, match="expected"):
            load_task_jsonl(p)

    def test_loads_valid_tasks(self, tmp_path: Path):
        p = tmp_path / "tasks.jsonl"
        tasks = [
            {"id": "t1", "prompt": "p1", "expected": "e1"},
            {"id": "t2", "prompt": "p2", "expected": "e2"},
        ]
        p.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
        result = load_task_jsonl(p)
        assert len(result) == 2
        assert result[0]["id"] == "t1"

    def test_skips_comment_lines(self, tmp_path: Path):
        p = tmp_path / "tasks.jsonl"
        p.write_text("# comment\n" + json.dumps({"id": "t1", "prompt": "p", "expected": "e"}) + "\n")
        result = load_task_jsonl(p)
        assert len(result) == 1
