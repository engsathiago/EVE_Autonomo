"""
Integration test for the finetune pipeline.

Requires:
  - RUN_FINETUNE_INTEGRATION=1
  - A real PostgreSQL instance with migration 014_finetune.sql applied
  - Ollama running at OLLAMA_BASE_URL with the base model loaded
  - GPU with >= 12 GiB VRAM

Run with:
  RUN_FINETUNE_INTEGRATION=1 pytest tests/finetune/test_integration_train.py -v -s
"""

from __future__ import annotations

import os

import pytest

_GUARD = os.getenv("RUN_FINETUNE_INTEGRATION", "0") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not _GUARD, reason="Set RUN_FINETUNE_INTEGRATION=1 to run"),
]


def test_finetune_module_imports():
    """Smoke test: all finetune submodules import without error."""
    from agent.finetune import (  # noqa: F401
        benchmark_runner,
        checkpoint_gate,
        checkpoint_registry,
        dataset_builder,
        exceptions,
        lora_trainer,
        reports,
        rubric,
        safety_check,
        trace_collector,
    )


def test_rubric_loads_from_project_benchmarks():
    """Verifies benchmarks/rubric.yaml can be loaded (weights valid, axes non-empty)."""
    from pathlib import Path

    from agent.finetune.rubric import Rubric

    project_root = Path(__file__).parents[4]
    rubric_path = project_root / "benchmarks" / "rubric.yaml"
    assert rubric_path.exists(), f"rubric.yaml not found at {rubric_path}"

    rubric = Rubric.load(rubric_path)
    assert len(rubric.axes) >= 1
    total = sum(a.weight for a in rubric.axes)
    assert abs(total - 1.0) < 0.01


def test_all_benchmark_task_files_valid():
    """Validates that every tasks/*.jsonl referenced in rubric.yaml is loadable."""
    from pathlib import Path

    from agent.finetune.rubric import Rubric, load_task_jsonl

    project_root = Path(__file__).parents[4]
    benchmarks_dir = project_root / "benchmarks"
    rubric = Rubric.load(benchmarks_dir / "rubric.yaml")

    for axis in rubric.axes:
        tasks_dir = benchmarks_dir / axis.tasks_dir
        if tasks_dir.exists():
            for jsonl_file in tasks_dir.glob("*.jsonl"):
                tasks = load_task_jsonl(jsonl_file)
                assert len(tasks) > 0, f"Empty task file: {jsonl_file}"


@pytest.mark.asyncio
async def test_trace_collector_runs_against_real_db():
    """Runs TraceCollector.collect() against the real DB (may return empty list)."""
    import asyncpg

    from agent.finetune.trace_collector import TraceCollector

    db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        collector = TraceCollector(pool=pool, lookback_days=7)
        records = await collector.collect()
        # May be empty — just verify no exception and correct structure
        assert isinstance(records, list)
        for r in records:
            assert "origin" in r
            assert "input" in r
            assert "output" in r
    finally:
        await pool.close()
