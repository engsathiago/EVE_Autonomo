"""C.5 — Validação runtime Fase 9 (Voyager Skills).

Valida:
  1. Tabela skills: SkillRegistry.save() persiste skill com status 'active'.
  2. Tabela skill_executions: SkillRegistry.record_execution() persiste execução.

Não executa código de skill real — apenas os caminhos de persistência em Postgres.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.runtime

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_REPO / "core" / "src"))

# Embedding de 384 dimensões com valor uniforme (vetor fake válido)
_FAKE_EMBEDDING = [0.01] * 384


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    yield pool
    await pool.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(slug: str):
    """Cria SkillManifestF9 mínimo válido para testes."""
    from agent.skills.manifest import NetworkPolicy, SkillManifestF9

    return SkillManifestF9(
        slug=slug,
        version=1,
        created_at=datetime.now(tz=UTC),
        description="Skill de validação runtime C.5",
        embedding_text="runtime test skill para validar persistência",
        inputs_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        outputs_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        sandbox_profile="DEFAULT",
        network_policy=NetworkPolicy(allow_domains=[]),
        irreversible=False,
    )


# ---------------------------------------------------------------------------
# Teste 1: skills — save + promoção para active
# ---------------------------------------------------------------------------


async def test_skill_registry_save_and_promote_to_active(pg_pool, tmp_path):
    """SkillRegistry.save() persiste skill; update_status→active confirma."""
    from agent.skills.registry import SkillRegistry

    registry = SkillRegistry(pool=pg_pool)

    slug = "rt_test_c5_skill_v1"
    manifest = _make_manifest(slug)

    await registry.save(manifest, _FAKE_EMBEDDING, status="pending")

    row = await pg_pool.fetchrow("SELECT * FROM skills WHERE slug = $1", slug)
    assert row is not None, f"skills não tem linha para slug={slug}"
    assert row["slug"] == slug
    assert row["status"] == "pending"

    # Promove para active
    await registry.update_status(slug, "active")

    row2 = await pg_pool.fetchrow("SELECT status FROM skills WHERE slug = $1", slug)
    assert row2["status"] == "active"

    # Evidência
    dest = Path(__file__).parent / "f9_skill_slug.txt"
    dest.write_text(slug)
    print(f"\n[C.5] skills INSERT+PROMOTE OK → slug={slug}")


# ---------------------------------------------------------------------------
# Teste 2: skill_executions
# ---------------------------------------------------------------------------


async def test_skill_registry_record_execution_persists(pg_pool, tmp_path):
    """SkillRegistry.record_execution() persiste em skill_executions com FK válida."""
    from agent.skills.registry import SkillRegistry

    registry = SkillRegistry(pool=pg_pool)

    # Garante que a skill existe (FK skills(slug))
    slug = "rt_test_c5_exec_skill"
    manifest = _make_manifest(slug)
    await registry.save(manifest, _FAKE_EMBEDDING, status="active")

    exec_id = await registry.record_execution(
        slug,
        success=True,
        duration_seconds=0.042,
        input_data={"path": "/tmp/runtime-test"},
        output_data={"result": "ok"},
    )

    row = await pg_pool.fetchrow(
        "SELECT * FROM skill_executions WHERE id = $1", exec_id
    )
    assert row is not None, f"skill_executions não tem linha para id={exec_id}"
    assert row["skill_slug"] == slug
    assert row["success"] is True

    # Evidência
    dest = Path(__file__).parent / "f9_skill_execution_id.txt"
    dest.write_text(exec_id)
    print(f"\n[C.5] skill_executions INSERT OK → exec_id={exec_id}")


# ---------------------------------------------------------------------------
# Teste 3: list skills por status
# ---------------------------------------------------------------------------


async def test_skill_registry_list_active(pg_pool):
    """SkillRegistry.list(status='active') retorna skills persistidas."""
    from agent.skills.registry import SkillRegistry

    registry = SkillRegistry(pool=pg_pool)

    slug = "rt_test_c5_list_skill"
    manifest = _make_manifest(slug)
    await registry.save(manifest, _FAKE_EMBEDDING, status="active")

    active = await registry.list(status="active")
    slugs = [r["slug"] for r in active]
    assert slug in slugs, f"slug={slug} não encontrado em skills(status=active)"
    print(f"\n[C.5] list(active) OK → {len(active)} skills ativas encontradas")
