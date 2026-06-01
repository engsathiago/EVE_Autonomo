"""Testes do SkillSynthesizer — C1: detecção de cluster."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.skills.synthesizer import (
    _MIN_CLUSTER_SIZE,
    _MIN_COSINE,
    ExecutionCluster,
    SkillSynthesizer,
)


def _make_pool(rows: list[dict] | None = None) -> MagicMock:
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=rows or [])
    return pool


def _make_cluster(n: int = 5, score: float = 0.9) -> ExecutionCluster:
    return ExecutionCluster(
        cluster_id="abc12345",
        execution_ids=[f"exec_{i}" for i in range(n)],
        pattern_summary="python script for youtube transcript download",
        avg_duration_seconds=2.5,
        cosine_score=score,
    )


@pytest.mark.asyncio
async def test_scan_returns_empty_when_no_executions(tmp_path: Path) -> None:
    pool = _make_pool(rows=[])
    synth = SkillSynthesizer(db_pool=pool, output_dir=tmp_path)
    clusters = await synth.scan_for_candidates()
    assert clusters == []


@pytest.mark.asyncio
async def test_synthesize_fallback_generates_files(tmp_path: Path) -> None:
    """Sem model_router, usa template fallback."""
    pool = _make_pool()
    synth = SkillSynthesizer(db_pool=pool, output_dir=tmp_path, model_router=None)
    cluster = _make_cluster(n=6, score=0.91)
    result = await synth.synthesize(cluster)
    assert result.proposed_slug.startswith("auto_")
    assert "async def run(" in result.skill_py
    assert "sandbox_profile:" in result.manifest_yaml


@pytest.mark.asyncio
async def test_synthesize_writes_files_to_pending(tmp_path: Path) -> None:
    pool = _make_pool()
    synth = SkillSynthesizer(db_pool=pool, output_dir=tmp_path, model_router=None)
    cluster = _make_cluster(n=5, score=0.87)
    result = await synth.synthesize(cluster)
    skill_dir = synth.write_candidate(result)
    assert (skill_dir / "skill.py").exists()
    assert (skill_dir / "manifest.yaml").exists()


@pytest.mark.asyncio
async def test_synthesize_manifest_no_open_network(tmp_path: Path) -> None:
    """C14: skill sintetizada não pode ter network OPEN."""
    pool = _make_pool()
    synth = SkillSynthesizer(db_pool=pool, output_dir=tmp_path, model_router=None)
    cluster = _make_cluster()
    result = await synth.synthesize(cluster)
    assert "*" not in result.manifest_yaml
    assert "0.0.0.0" not in result.manifest_yaml


def test_parse_llm_output_valid() -> None:
    pool = _make_pool()
    synth = SkillSynthesizer(db_pool=pool, output_dir=Path("/tmp"))
    cluster = _make_cluster()
    raw = (
        "===SKILL_PY===\nasync def run(input: dict) -> dict:\n    return {}\n===MANIFEST_YAML===\nslug: test\n===END==="
    )
    skill_py, manifest_yaml = synth._parse_llm_output(raw, "test", cluster)
    assert "async def run" in skill_py
    assert "slug: test" in manifest_yaml


def test_parse_llm_output_invalid_raises() -> None:
    from agent.skills.exceptions import SkillSynthesisFailed

    pool = _make_pool()
    synth = SkillSynthesizer(db_pool=pool, output_dir=Path("/tmp"))
    cluster = _make_cluster()
    with pytest.raises(SkillSynthesisFailed):
        synth._parse_llm_output("sem delimitadores", "test", cluster)


def test_cluster_minimum_size() -> None:
    assert _MIN_CLUSTER_SIZE == 5


def test_cluster_minimum_cosine() -> None:
    assert _MIN_COSINE == 0.85
