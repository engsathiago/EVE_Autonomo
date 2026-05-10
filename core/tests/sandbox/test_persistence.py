"""
Cobre §8 critério 6: migration 009_sandbox_executions aplica e linha é gravada.
Requer Postgres (marcado como integration — pula sem -m integration ou sem DB).
"""
from __future__ import annotations

import pytest
import pytest_asyncio


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Migration idempotente
# ---------------------------------------------------------------------------

async def test_migration_applies_idempotent(tmpdb):
    """Rodar a migration duas vezes não deve gerar erro (IF NOT EXISTS)."""
    from pathlib import Path
    sql = (
        Path(__file__).parents[2] / "migrations" / "009_sandbox_executions.sql"
    ).read_text()
    # Segunda aplicação — não deve lançar exceção
    async with tmpdb.acquire() as conn:
        await conn.execute(sql)  # já foi aplicada pelo fixture, aplicar de novo é idempotente


async def test_migration_creates_table(tmpdb):
    row = await tmpdb.fetchrow(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='sandbox_executions'"
    )
    assert row is not None


async def test_migration_creates_indexes(tmpdb):
    """Índices criados pela migration devem existir."""
    indexes = await tmpdb.fetch(
        "SELECT indexname FROM pg_indexes "
        "WHERE tablename='sandbox_executions'"
    )
    names = {r["indexname"] for r in indexes}
    assert "idx_sandbox_exec_mission" in names
    assert "idx_sandbox_exec_created" in names
    assert "idx_sandbox_exec_policy" in names


# ---------------------------------------------------------------------------
# Inserção de linha via SandboxRegistry
# ---------------------------------------------------------------------------

async def test_registry_record_inserts_row(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.sandbox.base import SandboxResult

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    result = SandboxResult(
        exit_code=0,
        stdout="hello",
        stderr="",
        duration_ms=123,
        cpu_seconds=0.12,
        memory_peak_mb=10.0,
        timed_out=False,
        oom_killed=False,
        network_denied_attempts=[],
    )

    sid = reg.new_id()
    await reg.record(
        sandbox_id=sid,
        policy_name="default",
        backend="subprocess",
        command="echo hello",
        result=result,
    )

    row = await tmpdb.fetchrow(
        "SELECT * FROM sandbox_executions WHERE id=$1", sid
    )
    assert row is not None
    assert row["exit_code"] == 0
    assert row["duration_ms"] == 123
    assert row["policy_name"] == "default"
    assert row["backend"] == "subprocess"
    assert row["stdout_preview"] == "hello"
    assert row["timed_out"] == 0
    assert row["oom_killed"] == 0


async def test_registry_stores_mission_and_subagent(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.sandbox.base import SandboxResult

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    result = SandboxResult(
        exit_code=0, stdout="", stderr="",
        duration_ms=10, cpu_seconds=0.01, memory_peak_mb=0.0,
        timed_out=False, oom_killed=False, network_denied_attempts=[],
    )

    sid = reg.new_id()
    await reg.record(
        sandbox_id=sid,
        policy_name="default",
        backend="subprocess",
        command="echo",
        result=result,
        mission_id="m-123",
        subagent_id="s-456",
    )

    row = await tmpdb.fetchrow("SELECT mission_id, subagent_id FROM sandbox_executions WHERE id=$1", sid)
    assert row["mission_id"] == "m-123"
    assert row["subagent_id"] == "s-456"


async def test_registry_stores_timed_out_flag(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.sandbox.base import SandboxResult

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    result = SandboxResult(
        exit_code=-1, stdout="", stderr="",
        duration_ms=1000, cpu_seconds=1.0, memory_peak_mb=0.0,
        timed_out=True, oom_killed=False, network_denied_attempts=[],
    )

    sid = reg.new_id()
    await reg.record(
        sandbox_id=sid,
        policy_name="default",
        backend="subprocess",
        command="sleep 999",
        result=result,
    )

    row = await tmpdb.fetchrow("SELECT timed_out FROM sandbox_executions WHERE id=$1", sid)
    assert row["timed_out"] == 1


async def test_registry_command_preview_at_200_chars(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.sandbox.base import SandboxResult

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    long_cmd = "echo " + "A" * 500
    result = SandboxResult(
        exit_code=0, stdout="", stderr="",
        duration_ms=10, cpu_seconds=0.01, memory_peak_mb=0.0,
        timed_out=False, oom_killed=False, network_denied_attempts=[],
    )

    sid = reg.new_id()
    await reg.record(
        sandbox_id=sid,
        policy_name="default",
        backend="subprocess",
        command=long_cmd,
        result=result,
    )

    row = await tmpdb.fetchrow("SELECT command_preview FROM sandbox_executions WHERE id=$1", sid)
    assert len(row["command_preview"]) <= 200
