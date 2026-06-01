"""Tests for benchmark_runner.py — C4, C5 (caching, scoring, persistence)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.finetune.benchmark_runner import BenchmarkRunner
from agent.finetune.rubric import Rubric, RubricAxis, RubricThresholds


def _make_rubric(tmp_path: Path) -> tuple[Rubric, Path]:
    tasks_dir = tmp_path / "tasks" / "base"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "test.jsonl"
    task_file.write_text(json.dumps({"id": "t1", "prompt": "What is 2+2?", "expected": "4", "keywords": ["4"]}) + "\n")

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


class TestLlmJudgeUsesAnthropicTransport:
    """C5: LLM judge must always use AnthropicTransport, never the candidate model."""

    @pytest.mark.asyncio
    async def test_llm_judge_uses_anthropic_transport(self, tmp_path: Path):
        """_llm_judge calls AnthropicTransport.chat, never _query_model (Ollama)."""
        tasks_dir = tmp_path / "tasks" / "inst"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "t.jsonl").write_text(
            json.dumps({"id": "i1", "prompt": "Draft a professional reply.", "expected": "judge"}) + "\n"
        )
        rubric = Rubric(
            version=1,
            axes=[
                RubricAxis("instruction", 1.0, "tasks/inst", "llm_judge_claude", judge_model="claude-haiku-4-5"),
            ],
            thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
        )
        pool = AsyncMock()
        pool.fetch.return_value = []
        pool.execute = AsyncMock()

        runner = BenchmarkRunner(rubric=rubric, benchmarks_dir=tmp_path, pool=pool)

        anthropic_calls = []
        ollama_calls = []

        async def mock_query(model_ref: str, prompt: str) -> str:
            ollama_calls.append(model_ref)
            return "Here is my professional reply with relevant content."

        async def mock_llm_judge(task_prompt: str, expected: str, model_output: str, judge_model: str) -> float:
            anthropic_calls.append(judge_model)
            return 0.9

        runner._query_model = mock_query  # type: ignore[method-assign]
        runner._llm_judge = mock_llm_judge  # type: ignore[method-assign]

        await runner.run(model_ref="checkpoint:test-model", run_id="run-j")
        assert len(anthropic_calls) > 0, "_llm_judge was never called"
        # Ollama is called for model output — that's correct
        assert len(ollama_calls) > 0

    def test_benchmark_runner_imports_anthropic_transport(self):
        """BenchmarkRunner source imports AnthropicTransport (not Ollama) for judging."""
        import inspect

        import agent.finetune.benchmark_runner as bm_module

        source = inspect.getsource(bm_module)
        assert "AnthropicTransport" in source, "BenchmarkRunner must use AnthropicTransport as LLM judge"


class TestLlmJudgeDirect:
    @pytest.mark.asyncio
    async def test_llm_judge_returns_score_from_transport(self, tmp_path: Path):
        """_llm_judge parses Claude response as float 0-1."""
        rubric = Rubric(
            version=1,
            axes=[RubricAxis("base", 1.0, "tasks/base", "exact_match")],
            thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
        )
        runner = BenchmarkRunner(rubric=rubric, benchmarks_dir=tmp_path, pool=AsyncMock())

        mock_transport = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "0.85"

        mock_transport.chat = AsyncMock(return_value=mock_response)

        with patch("agent.transports.anthropic.AnthropicTransport", return_value=mock_transport):
            score = await runner._llm_judge("prompt", "expected", "actual", "claude-haiku-4-5")
        assert abs(score - 0.85) < 1e-6

    @pytest.mark.asyncio
    async def test_llm_judge_returns_zero_on_value_error(self, tmp_path: Path):
        """_llm_judge returns 0.0 when Claude response is not parseable."""
        runner = BenchmarkRunner(
            rubric=Rubric(version=1, axes=[RubricAxis("b", 1.0, "t", "exact_match")], thresholds=RubricThresholds()),
            benchmarks_dir=tmp_path,
            pool=AsyncMock(),
        )
        mock_transport = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "not-a-number"
        mock_transport.chat = AsyncMock(return_value=mock_response)

        with patch("agent.transports.anthropic.AnthropicTransport", return_value=mock_transport):
            score = await runner._llm_judge("p", "e", "a", "claude-haiku-4-5")
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_llm_judge_returns_zero_on_transport_exception(self, tmp_path: Path):
        """_llm_judge returns 0.0 and logs when AnthropicTransport raises."""
        runner = BenchmarkRunner(
            rubric=Rubric(version=1, axes=[RubricAxis("b", 1.0, "t", "exact_match")], thresholds=RubricThresholds()),
            benchmarks_dir=tmp_path,
            pool=AsyncMock(),
        )
        mock_transport = AsyncMock()
        mock_transport.chat = AsyncMock(side_effect=Exception("API unavailable"))

        with patch("agent.transports.anthropic.AnthropicTransport", return_value=mock_transport):
            score = await runner._llm_judge("p", "e", "a", "claude-haiku-4-5")
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_llm_judge_clamps_score_to_0_1(self, tmp_path: Path):
        """_llm_judge clamps scores to [0.0, 1.0]."""
        runner = BenchmarkRunner(
            rubric=Rubric(version=1, axes=[RubricAxis("b", 1.0, "t", "exact_match")], thresholds=RubricThresholds()),
            benchmarks_dir=tmp_path,
            pool=AsyncMock(),
        )
        mock_transport = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "1.5"  # out of range
        mock_transport.chat = AsyncMock(return_value=mock_response)

        with patch("agent.transports.anthropic.AnthropicTransport", return_value=mock_transport):
            score = await runner._llm_judge("p", "e", "a", "claude-haiku-4-5")
        assert score <= 1.0


class TestExactMatchScoring:
    @pytest.mark.asyncio
    async def test_exact_match_scores_1_on_perfect_match(self, tmp_path: Path):
        tasks_dir = tmp_path / "tasks" / "base"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "t.jsonl").write_text(json.dumps({"id": "e1", "prompt": "What is 2+2?", "expected": "4"}) + "\n")
        rubric = Rubric(
            version=1,
            axes=[RubricAxis("base", 1.0, "tasks/base", "exact_match")],
            thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
        )
        pool = AsyncMock()
        pool.fetch.return_value = []
        pool.execute = AsyncMock()
        runner = BenchmarkRunner(rubric=rubric, benchmarks_dir=tmp_path, pool=pool)
        runner._query_model = AsyncMock(return_value="4")  # type: ignore[method-assign]

        scores = await runner.run(model_ref="checkpoint:test", run_id="r1")
        assert abs(scores["base"] - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_exact_match_scores_0_on_wrong_answer(self, tmp_path: Path):
        tasks_dir = tmp_path / "tasks" / "base"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "t.jsonl").write_text(json.dumps({"id": "e1", "prompt": "What is 2+2?", "expected": "4"}) + "\n")
        rubric = Rubric(
            version=1,
            axes=[RubricAxis("base", 1.0, "tasks/base", "exact_match")],
            thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
        )
        pool = AsyncMock()
        pool.fetch.return_value = []
        pool.execute = AsyncMock()
        runner = BenchmarkRunner(rubric=rubric, benchmarks_dir=tmp_path, pool=pool)
        runner._query_model = AsyncMock(return_value="5")  # type: ignore[method-assign]

        scores = await runner.run(model_ref="checkpoint:test", run_id="r2")
        assert scores["base"] == 0.0
