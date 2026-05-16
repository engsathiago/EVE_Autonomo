"""Tests for benchmark_runner.py — C4, C5 (caching, scoring, persistence)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.finetune.benchmark_runner import BenchmarkRunner
from agent.finetune.rubric import Rubric, RubricAxis, RubricThresholds


def _make_rubric(tmp_path: Path) -> tuple[Rubric, Path]:
    tasks_dir = tmp_path / "tasks" / "base"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "test.jsonl"
    task_file.write_text(
        json.dumps({"id": "t1", "prompt": "What is 2+2?", "expected": "4", "keywords": ["4"]}) + "\n"
    )

    rubric = Rubric(
        version=1,
        axes=[
            RubricAxis("base_capabilities", 1.0, "tasks/base", "exact_match_or_keyword"),
        ],
        thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
    )
    return rubric, tmp_path


class TestBenchmarkRunner:
    @pytest.mark.asyncio
    async def test_uses_cache_for_base_model(self, tmp_path: Path):
        """C5: cache hit avoids re-running benchmark."""
        rubric, benchmarks_dir = _make_rubric(tmp_path)
        pool = AsyncMock()
        pool.fetch.return_value = [{"rubric_axis": "base_capabilities", "avg_score": 0.85}]

        runner = BenchmarkRunner(
            rubric=rubric,
            benchmarks_dir=benchmarks_dir,
            pool=pool,
            base_score_cache_days=7,
        )
        scores = await runner.run(model_ref="base:qwen2.5-7b", run_id=None)
        assert scores == {"base_capabilities": 0.85}
        # Ollama was never called because cache was hit
        pool.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_cache_for_checkpoint(self, tmp_path: Path):
        """C4: checkpoint model always runs fresh (no cache lookup)."""
        rubric, benchmarks_dir = _make_rubric(tmp_path)
        pool = AsyncMock()
        pool.fetch.return_value = []
        pool.execute = AsyncMock()

        runner = BenchmarkRunner(
            rubric=rubric,
            benchmarks_dir=benchmarks_dir,
            pool=pool,
        )

        async def mock_query(model_ref: str, prompt: str) -> str:
            return "4"

        runner._query_model = mock_query  # type: ignore[method-assign]
        scores = await runner.run(model_ref="checkpoint:qwen-ft-abc123", run_id="run-1")
        assert "base_capabilities" in scores
        # No cache lookup for checkpoint
        pool.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_benchmark_results(self, tmp_path: Path):
        """C4: results persisted in benchmark_results table."""
        rubric, benchmarks_dir = _make_rubric(tmp_path)
        pool = AsyncMock()
        pool.fetch.return_value = []  # no cache
        pool.execute = AsyncMock()

        runner = BenchmarkRunner(
            rubric=rubric,
            benchmarks_dir=benchmarks_dir,
            pool=pool,
        )

        async def mock_query(model_ref: str, prompt: str) -> str:
            return "4"

        runner._query_model = mock_query  # type: ignore[method-assign]
        await runner.run(model_ref="base:qwen2.5-7b", run_id="run-1")
        # Should have called execute to persist results
        pool.execute.assert_called()

    def test_rouge_l_perfect_match(self):
        """ROUGE-L returns 1.0 for identical strings."""
        score = BenchmarkRunner._rouge_l("the quick brown fox", "the quick brown fox")
        assert abs(score - 1.0) < 1e-6

    def test_rouge_l_no_overlap(self):
        """ROUGE-L returns 0.0 for completely different strings."""
        score = BenchmarkRunner._rouge_l("abc def", "xyz uvw")
        assert score == 0.0

    def test_score_refusal_detected(self):
        task = {"id": "s1", "prompt": "bad prompt", "expected": "refusal"}
        score = BenchmarkRunner._score_refusal("Não posso ajudar com isso.", task)
        assert score == 1.0

    def test_score_refusal_not_detected(self):
        task = {"id": "s1", "prompt": "bad prompt", "expected": "refusal"}
        score = BenchmarkRunner._score_refusal("Sure, here is how to do it.", task)
        assert score == 0.0
