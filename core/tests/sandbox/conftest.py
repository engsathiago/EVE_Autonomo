"""
Fixtures compartilhados para testes da Fase 8 (Sandboxes).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from agent.observability.logger import configure_logging
from agent.sandbox.base import NetworkPolicy, SandboxConfig
from agent.sandbox.subprocess_backend import SubprocessSandbox

configure_logging("WARNING")


# ---------------------------------------------------------------------------
# Factory injetável — __module__ controlado para não confundir registry
# ---------------------------------------------------------------------------


def make_subprocess_sandbox(config: SandboxConfig) -> SubprocessSandbox:
    """Factory de SubprocessSandbox para injeção em exec_tool nos testes."""
    return SubprocessSandbox(config)


# O módulo desta função é "tests.sandbox.conftest"; o backend_name gravado
# no DB será "conftest" — aceitável pois é só informativo.


# ---------------------------------------------------------------------------
# Configs de base
# ---------------------------------------------------------------------------


@pytest.fixture
def deny_all_config() -> SandboxConfig:
    return SandboxConfig(
        cpu_limit=1.0,
        memory_limit_mb=512,
        wall_time_seconds=30,
        network=NetworkPolicy.DENY_ALL,
        max_output_bytes=1_000_000,
    )


@pytest.fixture
def fast_config() -> SandboxConfig:
    """Config rápida para testes de timeout: 2s wall time."""
    return SandboxConfig(
        cpu_limit=1.0,
        memory_limit_mb=512,
        wall_time_seconds=2,
        network=NetworkPolicy.DENY_ALL,
        max_output_bytes=1_000_000,
    )


@pytest.fixture
def sandbox_factory():
    """Retorna a factory de SubprocessSandbox para injeção em exec_tool."""
    return make_subprocess_sandbox


# ---------------------------------------------------------------------------
# Log dir temporário
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_log_dir(tmp_path: Path) -> Path:
    log_dir = tmp_path / "logs" / "sandbox"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


# ---------------------------------------------------------------------------
# Event collector — registra handler, remove após o teste
# ---------------------------------------------------------------------------


@pytest.fixture
def event_collector() -> list[dict[str, Any]]:
    """
    Registra handler no event_registry de sandbox e coleta eventos emitidos.
    Remove o handler ao fim do teste para não poluir outros testes.
    """
    from agent.events import _sandbox_handlers

    collected: list[dict[str, Any]] = []

    def handler(event_type: str, data: dict[str, Any]) -> None:
        collected.append({"type": event_type, "data": data})

    _sandbox_handlers.append(handler)
    yield collected
    # Cleanup: remove handler da lista global
    try:
        _sandbox_handlers.remove(handler)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# tmpdb — Postgres de teste, aplica migration 009
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tmpdb():
    """
    Pool asyncpg para testes de persistência.
    Pula automaticamente se POSTGRES_DSN não está disponível.
    Aplica migration 009 e faz DROP TABLE ao fim.
    """
    import asyncpg

    dsn = os.getenv("POSTGRES_DSN", "postgresql://agent:agent@postgres:5432/agent")
    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2, command_timeout=5)
        # Testa conectividade
        await pool.fetchval("SELECT 1")
    except Exception as exc:
        pytest.skip(f"Postgres não disponível ({exc}) — pule com -m 'not integration'")
        return

    migration_path = Path(__file__).parents[2] / "migrations" / "009_sandbox_executions.sql"
    migration_sql = migration_path.read_text()

    async with pool.acquire() as conn:
        await conn.execute(migration_sql)

    yield pool

    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS sandbox_executions CASCADE")

    await pool.close()
