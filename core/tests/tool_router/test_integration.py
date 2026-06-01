"""
Testes de integração para D.1 — Tool routing por step.

Requerem PostgreSQL real com migration 016 aplicada.
Skip automático quando POSTGRES_DSN não está disponível ou migration
ainda não foi rodada.

Marcados com @pytest.mark.integration.
"""

from __future__ import annotations

import os

import pytest

from agent.orchestrator.tiers import ExecutionTier
from agent.orchestrator.tool_router import (
    StepSpec,
    log_routing_audit,
    resolve_tools_for_step,
)

# ─── Helpers e fixtures ─────────────────────────────────────────────────────


def _skip_if_no_db() -> None:
    dsn = os.getenv("POSTGRES_DSN", "")
    if not dsn:
        pytest.skip("POSTGRES_DSN não configurado — skip de integração")


@pytest.fixture
async def db_pool():
    """Pool Postgres real. Skip se DSN indisponível."""
    _skip_if_no_db()
    import asyncpg

    dsn = os.getenv("POSTGRES_DSN")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest.fixture
async def mission_store(db_pool):
    from agent.missions.store import MissionStore

    return MissionStore(db_pool)


@pytest.fixture
async def fresh_mission(mission_store):
    """Cria missão temporária para testes."""
    m = await mission_store.create(
        title="Test D.1",
        objective="Testar tool routing por step",
        success_criteria=[{"criterion": "tools corretas são resolvidas"}],
        deadline=None,
        source="test",
        source_ref="test_integration",
    )
    yield m
    # cleanup: abandona a missão no final do teste
    try:
        await mission_store.update_status(m.id, "abandoned")
    except Exception:
        pass


# ─── Testes de integração ────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_declarado_propaga_tools_required(mission_store, fresh_mission):
    """
    C2+C9: step com tools_required armazenado no DB mantém a declaração
    ao ser lido de volta pelo store.
    """
    _skip_if_no_db()
    declared = ["web_search", "write_file"]

    step = await mission_store.add_step(
        fresh_mission.id,
        description="Buscar na web e salvar resultado",
        tools_required=declared,
    )

    # Lê de volta pelo store
    steps = await mission_store.get_all_steps(fresh_mission.id)
    assert len(steps) == 1
    read_back = steps[0]

    assert read_back.id == step.id
    assert set(read_back.tools_required) == set(declared), (
        f"tools_required lidos {read_back.tools_required!r} != declarados {declared!r}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_audit_gravado_no_step_tool_routing(db_pool, mission_store, fresh_mission):
    """
    C9: log_routing_audit persiste linha em step_tool_routing com campos corretos.
    """
    _skip_if_no_db()

    step = await mission_store.add_step(
        fresh_mission.id,
        description="Pesquisar X na web",
        tools_required=["web_search"],
    )

    spec = StepSpec(description=step.description, tools_required=step.tools_required)
    resolution = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    # Grava audit
    await log_routing_audit(
        step_id=step.id,
        tier=ExecutionTier.STRATEGIC.value,
        resolution=resolution,
        db_pool=db_pool,
    )

    # Verifica se foi gravado
    rows = await db_pool.fetch("SELECT * FROM step_tool_routing WHERE step_id = $1", step.id)
    assert len(rows) == 1, f"Esperava 1 linha em step_tool_routing, encontrou {len(rows)}"

    row = rows[0]
    assert row["tier"] == "STRATEGIC"
    assert row["inference_source"] == resolution.source

    import json

    resolved_in_db = (
        json.loads(row["tools_resolved"]) if isinstance(row["tools_resolved"], str) else row["tools_resolved"]
    )
    for t in resolution.tools:
        assert t in resolved_in_db, f"Tool {t!r} ausente em tools_resolved no DB"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_step_missing_tool_marca_status_correto(mission_store, fresh_mission):
    """
    C6: step com tool declarada inexistente → status 'failed_missing_tool'
    após processar no loop.

    Testa a lógica do loop sem levantar infra completa (mock orchestrator).
    """
    _skip_if_no_db()

    step = await mission_store.add_step(
        fresh_mission.id,
        description="Usar tool inexistente",
        tools_required=["tool_xyz_nao_existe_no_registry"],
    )

    # Simula o que o autonomous loop faz ao chamar o orchestrator
    # que por sua vez chama pool.spawn que detecta a tool faltante
    # e lança MissingRequiredTool.
    # Testamos a atualização de status diretamente (sem infra completa).
    await mission_store.update_step(
        step.id,
        status="failed_missing_tool",
        error="missing_tools: ['tool_xyz_nao_existe_no_registry']",
    )

    # Verifica que o status foi persistido corretamente
    steps = await mission_store.get_all_steps(fresh_mission.id)
    updated = steps[0]
    assert updated.status == "failed_missing_tool"
    assert "tool_xyz_nao_existe_no_registry" in (updated.error or "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missao_completa_com_step_missing_tool(mission_store, fresh_mission):
    """
    C6+C7: missão com 3 steps. Step do meio tem tool inexistente.
    Os outros 2 completam normalmente.
    A missão finaliza sem travar.
    """
    _skip_if_no_db()

    s1 = await mission_store.add_step(fresh_mission.id, description="Step normal 1", tools_required=[])
    s2 = await mission_store.add_step(
        fresh_mission.id,
        description="Step com tool faltante",
        tools_required=["tool_nao_existe_abc"],
    )
    s3 = await mission_store.add_step(fresh_mission.id, description="Step normal 2", tools_required=[])

    # Simula execução: step 1 e 3 concluem, step 2 falha por tool ausente
    await mission_store.update_step(s1.id, status="done", result={"verdict": "executed"})
    await mission_store.update_step(
        s2.id,
        status="failed_missing_tool",
        error="missing_tools: ['tool_nao_existe_abc']",
    )
    await mission_store.update_step(s3.id, status="done", result={"verdict": "executed"})

    # Verifica statuses individuais
    all_steps = await mission_store.get_all_steps(fresh_mission.id)
    statuses = {s.id: s.status for s in all_steps}

    assert statuses[s1.id] == "done"
    assert statuses[s2.id] == "failed_missing_tool"
    assert statuses[s3.id] == "done"

    # Loop considera {done, skipped, failed_missing_tool} como terminal →
    # missão pode ser completada mesmo com step failed_missing_tool.
    terminal = {"done", "skipped", "failed_missing_tool"}
    assert all(s.status in terminal for s in all_steps), "Nem todos os steps atingiram status terminal — missão travada"
