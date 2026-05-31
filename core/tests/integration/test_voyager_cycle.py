"""
Teste de integração do ciclo Voyager (F9):
scan_for_candidates → synthesize → write_candidate → save_candidate

Requer PostgreSQL rodando. Skip automático se indisponível.
"""

import uuid
from pathlib import Path

import pytest


@pytest.fixture
async def db_pool():
    try:
        import asyncpg

        pool = await asyncpg.create_pool(
            host="localhost",
            port=5432,
            user="agent",
            password="qualquercoisa123",
            database="agent",
            min_size=1,
            max_size=2,
        )
        yield pool
        await pool.close()
    except Exception:
        pytest.skip("PostgreSQL indisponível")


@pytest.fixture
def tmp_skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills_auto"
    d.mkdir()
    return d


@pytest.mark.asyncio
async def test_voyager_cycle_end_to_end(db_pool, tmp_skills_dir):
    """Ciclo completo: scan → synthesize → write → save_candidate."""
    from datetime import UTC, datetime, timedelta

    from agent.skills.registry import SkillRegistry
    from agent.skills.synthesizer import SkillSynthesizer

    # 1. Inserir 6 sandbox_executions com mesmo command_preview (cosine=1.0)
    unique_cmd = f"python3 -c 'print(\"voyager_test_{uuid.uuid4().hex[:8]}\")"
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=60)

    for i in range(6):
        await db_pool.execute(
            """
            INSERT INTO sandbox_executions (
                id, created_at, policy_name, backend,
                command_hash, command_preview,
                exit_code, duration_ms, memory_peak_mb,
                cpu_seconds, timed_out, oom_killed, network_denied_count
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            uuid.uuid4().hex,
            cutoff + timedelta(minutes=i),
            "default",
            "subprocess",
            uuid.uuid4().hex[:16],
            unique_cmd,
            0,  # exit_code
            200 + i * 10,
            64.0,
            0.2,
            0,  # timed_out (integer)
            0,  # oom_killed (integer)
            0,  # network_denied_count
        )

    # 2. scan_for_candidates
    synth = SkillSynthesizer(db_pool=db_pool, output_dir=tmp_skills_dir, model_router=None)
    clusters = await synth.scan_for_candidates()

    # Filtra só o cluster criado por este teste
    test_clusters = [
        c for c in clusters if any(unique_cmd[:40] in c.pattern_summary for c in [c])
    ]
    assert len(test_clusters) >= 1, f"Nenhum cluster encontrado para o cmd do teste. Clusters: {clusters}"

    cluster = test_clusters[0]
    assert len(cluster.execution_ids) >= 6
    assert cluster.cosine_score >= 0.85

    # 3. synthesize (template fallback — model_router=None)
    result = await synth.synthesize(cluster)
    assert result.proposed_slug.startswith("auto_")
    assert "async def run" in result.skill_py
    assert "slug:" in result.manifest_yaml

    # 4. write_candidate
    skill_dir = synth.write_candidate(result)
    assert (skill_dir / "skill.py").exists()
    assert (skill_dir / "manifest.yaml").exists()

    # 5. save_candidate
    registry = SkillRegistry(pool=db_pool)
    before = await db_pool.fetchval("SELECT count(*) FROM skill_candidates")
    candidate_id = await registry.save_candidate(
        proposed_slug=result.proposed_slug,
        source_execution_ids=cluster.execution_ids,
        pattern_cluster_score=cluster.cosine_score,
        status="synthesizing",
    )
    after = await db_pool.fetchval("SELECT count(*) FROM skill_candidates")

    assert after == before + 1
    assert candidate_id is not None
