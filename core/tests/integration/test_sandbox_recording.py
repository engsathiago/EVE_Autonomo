"""
Testa que exec_tool persiste em sandbox_executions quando db_pool fornecido.

Requer PostgreSQL rodando (skip automático se indisponível).
"""

import pytest


@pytest.fixture
async def db_pool():
    """Pool asyncpg para o postgres do Docker Compose."""
    try:
        import asyncpg
        pool = await asyncpg.create_pool(
            host="localhost", port=5432,
            user="agent", password="qualquercoisa123", database="agent",
            min_size=1, max_size=2,
        )
        yield pool
        await pool.close()
    except Exception:
        pytest.skip("PostgreSQL indisponível")


@pytest.mark.asyncio
async def test_exec_tool_records_sandbox_execution(db_pool):
    """exec_tool com SandboxRegistry → linha em sandbox_executions."""
    from agent.sandbox.registry import SandboxRegistry
    from agent.tools.exec_tool import exec_tool

    before = await db_pool.fetchval("SELECT count(*) FROM sandbox_executions")

    registry = SandboxRegistry(db_pool=db_pool)
    result = await exec_tool(
        ["python3", "-c", "print(42)"],
        policy_name="default",
        registry=registry,
    )

    after = await db_pool.fetchval("SELECT count(*) FROM sandbox_executions")
    assert result.exit_code == 0
    assert after == before + 1


@pytest.mark.asyncio
async def test_exec_tool_no_registry_no_error():
    """exec_tool sem registry não deve falhar."""
    from agent.tools.exec_tool import exec_tool

    result = await exec_tool(["python3", "-c", "print('ok')"])
    assert result.exit_code == 0
    assert "ok" in result.stdout
