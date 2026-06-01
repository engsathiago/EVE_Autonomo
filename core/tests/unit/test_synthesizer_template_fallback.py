"""Testa que SkillSynthesizer usa template quando model_router=None."""

import pytest

from agent.skills.synthesizer import ExecutionCluster, SkillSynthesizer


@pytest.fixture
def cluster():
    return ExecutionCluster(
        cluster_id="test1234",
        execution_ids=["id1", "id2", "id3", "id4", "id5"],
        pattern_summary="python3 -c 'print(2+2)'",
        avg_duration_seconds=0.25,
        cosine_score=0.97,
    )


@pytest.mark.asyncio
async def test_synthesize_with_no_model_router_uses_template(tmp_path, cluster):
    """model_router=None → usa _fallback_template, não chama LLM."""
    synth = SkillSynthesizer(db_pool=None, output_dir=tmp_path, model_router=None)
    result = await synth.synthesize(cluster)

    assert result.proposed_slug == "auto_test1234"
    assert "async def run" in result.skill_py
    assert "slug: auto_test1234" in result.manifest_yaml
    assert "sandbox_profile: SKILL_DEV" in result.manifest_yaml
    # Não tem network_policy wildcard
    assert "'*'" not in result.manifest_yaml
    assert '"*"' not in result.manifest_yaml


@pytest.mark.asyncio
async def test_synthesize_template_marks_source_executions(tmp_path, cluster):
    """Template fallback inclui IDs das execuções de origem no manifest."""
    synth = SkillSynthesizer(db_pool=None, output_dir=tmp_path, model_router=None)
    result = await synth.synthesize(cluster)

    # Provenance com execution ids
    assert "id1" in result.manifest_yaml
    assert "synthesized_from_template: auto" in result.manifest_yaml


@pytest.mark.asyncio
async def test_write_candidate_creates_files(tmp_path, cluster):
    """write_candidate cria skill.py + manifest.yaml no diretório correto."""
    synth = SkillSynthesizer(db_pool=None, output_dir=tmp_path, model_router=None)
    result = await synth.synthesize(cluster)
    skill_dir = synth.write_candidate(result)

    assert skill_dir == tmp_path / "auto_test1234"
    assert (skill_dir / "skill.py").exists()
    assert (skill_dir / "manifest.yaml").exists()
    # skill.py deve ter função run
    content = (skill_dir / "skill.py").read_text()
    assert "async def run" in content
