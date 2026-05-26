"""Shared fixtures for the finetune test suite (F13)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from agent.finetune.rubric import Rubric, RubricAxis, RubricThresholds

# Inject CLI src so test_cli.py can import `cli.finetune_cli`
_CLI_SRC = Path(__file__).parents[3] / "cli" / "src"
if str(_CLI_SRC) not in sys.path and _CLI_SRC.exists():
    sys.path.insert(0, str(_CLI_SRC))


@pytest.fixture
def fake_rubric() -> Rubric:
    """Minimal valid Rubric with two axes (weights sum to 1.0)."""
    return Rubric(
        version=1,
        axes=[
            RubricAxis("base_capabilities", 0.70, "tasks/base", "exact_match"),
            RubricAxis("safety", 0.30, "tasks/safety", "refusal_check"),
        ],
        thresholds=RubricThresholds(min_improvement_pct=3.0, max_regression_pct=5.0),
    )


@pytest.fixture
def fake_rubric_on_disk(tmp_path: Path) -> Path:
    """Writes a valid rubric.yaml to tmp_path/rubric.yaml and returns the path."""
    content = {
        "version": 1,
        "axes": [
            {"name": "base_capabilities", "weight": 0.70, "tasks_dir": "tasks/base", "judge": "exact_match"},
            {"name": "safety", "weight": 0.30, "tasks_dir": "tasks/safety", "judge": "refusal_check"},
        ],
        "thresholds": {"min_improvement_pct": 3.0, "max_regression_pct": 5.0},
    }
    p = tmp_path / "rubric.yaml"
    p.write_text(yaml.dump(content))
    return p


@pytest.fixture
def fake_traces() -> list[dict]:
    """Ten valid trace records with origin metadata."""
    records = []
    for i in range(10):
        records.append({
            "origin": {
                "trace_id": f"skill:exec_{i:04d}",
                "skill_id": "summarize_text",
                "mission_id": None,
                "type": "skill_execution",
            },
            "input": f"Summarize the following document carefully (record {i}): lorem ipsum dolor sit amet",
            "output": f"Summary of document {i}: brief synopsis of the content discussed",
            "context": {"skill_slug": "summarize_text", "duration_s": 1.2},
            "created_at": "2026-05-16T00:00:00Z",
        })
    return records


@pytest.fixture
def mock_pool() -> AsyncMock:
    """Minimal asyncpg pool mock with fetch/fetchrow/execute stubs."""
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value=None)
    pool.close = AsyncMock(return_value=None)
    return pool


@pytest.fixture
def tmp_models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    return d


@pytest.fixture
def tmp_benchmarks_dir(tmp_path: Path) -> Path:
    d = tmp_path / "benchmarks"
    d.mkdir()
    return d
