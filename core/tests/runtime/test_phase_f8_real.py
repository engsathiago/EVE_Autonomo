"""
C.4 — Runtime validation Fase 8 (Sandbox)

Valida exec_tool end-to-end com infra real:
  exec_tool(["python3", "-c", "print('hello')"], policy="default")
    → SubprocessSandbox executa de verdade
    → SandboxRegistry persiste em sandbox_executions (Postgres real)
    → SELECT confirma linha com exit_code=0

NÃO usa mocks. Requer Postgres em localhost:5432.
Rodar com: pytest -m runtime tests/runtime/test_phase_f8_real.py -v
"""
from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from agent.sandbox.subprocess_backend import SubprocessSandbox
from agent.sandbox.registry import SandboxRegistry
from agent.tools.exec_tool import exec_tool

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_EVIDENCE_DIR = Path(__file__).parent / "evidence"

pytestmark = pytest.mark.runtime


def _make_subprocess_sandbox(cfg):
    return SubprocessSandbox(cfg)


@pytest.fixture
async def pg_pool():
    try:
        pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    except Exception as exc:
        pytest.skip(f"Postgres indisponível em localhost:5432: {exc}")
    yield pool
    await pool.close()


async def test_exec_tool_hello_persists_to_postgres(pg_pool, tmp_path):
    """exec_tool print('hello') → exit_code=0, stdout contém hello, sandbox_executions ≥ 1."""
    registry = SandboxRegistry(db_pool=pg_pool, log_dir=tmp_path / "sandbox_logs")

    result = await exec_tool(
        ["python3", "-c", "print('hello')"],
        policy_name="default",
        make_sandbox=_make_subprocess_sandbox,
        registry=registry,
    )

    assert result.exit_code == 0, (
        f"Esperado exit_code=0, obtido {result.exit_code}. stderr: {result.stderr!r}"
    )
    assert "hello" in result.stdout, (
        f"'hello' não encontrado em stdout: {result.stdout!r}"
    )

    count = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM sandbox_executions WHERE exit_code = 0"
    )
    assert count >= 1, "Nenhuma linha com exit_code=0 em sandbox_executions"

    row = await pg_pool.fetchrow(
        "SELECT id, policy_name, exit_code FROM sandbox_executions"
        " WHERE command_preview LIKE $1"
        " ORDER BY created_at DESC LIMIT 1",
        "%print('hello')%",
    )
    assert row is not None, "Linha com command_preview contendo print('hello') não encontrada"
    assert row["policy_name"] == "default"
    assert row["exit_code"] == 0

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (_EVIDENCE_DIR / "f8_sandbox_exec_id.txt").write_text(
        f"sandbox_id={row['id']}\npolicy_name=default\nexit_code=0\nstdout=hello\n"
    )


async def test_exec_tool_nonzero_exit_also_persists(pg_pool, tmp_path):
    """Comando com exit_code != 0 ainda deve ser persistido em sandbox_executions."""
    registry = SandboxRegistry(db_pool=pg_pool, log_dir=tmp_path / "sandbox_logs")

    result = await exec_tool(
        ["python3", "-c", "import sys; sys.exit(42)"],
        policy_name="default",
        make_sandbox=_make_subprocess_sandbox,
        registry=registry,
    )

    assert result.exit_code == 42, (
        f"Esperado exit_code=42, obtido {result.exit_code}"
    )

    row = await pg_pool.fetchrow(
        "SELECT id, exit_code FROM sandbox_executions WHERE exit_code = 42"
        " ORDER BY created_at DESC LIMIT 1"
    )
    assert row is not None, "Linha com exit_code=42 não encontrada em sandbox_executions"
    assert row["exit_code"] == 42
