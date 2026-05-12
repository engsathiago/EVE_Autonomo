"""
Health check endpoints (F10).

Três níveis conforme §5.2:
  /health/live  — Liveness: só retorna 200. Nunca faz I/O.
  /health/ready — Readiness: checa SQLite, Postgres, scheduler, subagent pool.
  /health/deep  — Deep: readiness + executa skill noop real via exec_tool.

O router é criado por make_health_router() com injeção dos componentes
que precisam ser verificados. Registrado no server.py.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse


# ── noop skill ────────────────────────────────────────────────────────────────

_NOOP_SKILL_PY = b"""\
async def run(inputs):
    return {"ok": True}
"""

_RUNTIME_SCRIPT = """\
import asyncio, json, sys, importlib.util
spec = importlib.util.spec_from_file_location('skill', 'skill.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
data = json.loads(open('input.json').read())
result = asyncio.run(mod.run(data))
print(json.dumps(result))
"""


async def _run_noop_skill() -> dict[str, Any]:
    """Executa a skill noop via exec_tool em sandbox SUBPROCESS.

    Usa a mesma infra do SkillRunner (F9/F8) para validar que o caminho
    completo de execução está funcional.
    """
    from agent.tools.exec_tool import exec_tool
    from agent.sandbox.subprocess_backend import make_sandbox

    t0 = time.monotonic()
    result = await asyncio.wait_for(
        exec_tool(
            ["python", "-c", _RUNTIME_SCRIPT],
            policy_name="default",
            files={
                "skill.py": _NOOP_SKILL_PY,
                "input.json": b"{}",
            },
            make_sandbox=make_sandbox,
        ),
        timeout=2.0,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    ok = result.exit_code == 0 and '"ok": true' in result.stdout.lower()
    return {
        "ok": ok,
        "exit_code": result.exit_code,
        "duration_ms": elapsed_ms,
        "stdout": result.stdout[:200],
    }


# ── Checagens de readiness ─────────────────────────────────────────────────────

async def _check_sqlite() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        db_path = os.environ.get("AGENT_DB_SQLITE", "agent.db")
        # asyncio.to_thread para não bloquear o event loop
        import sqlite3

        def _ping() -> None:
            conn = sqlite3.connect(db_path, timeout=2)
            conn.execute("SELECT 1")
            conn.close()

        await asyncio.wait_for(asyncio.to_thread(_ping), timeout=2.0)
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "latency_ms": int((time.monotonic() - t0) * 1000)}


async def _check_postgres(db_pool: Any) -> dict[str, Any]:
    if db_pool is None:
        return {"ok": True, "skipped": True}  # Postgres não configurado neste ambiente
    t0 = time.monotonic()
    try:
        async with db_pool.acquire() as conn:
            await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=2.0)
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "latency_ms": int((time.monotonic() - t0) * 1000)}


def _check_scheduler(cron_worker: Any) -> dict[str, Any]:
    if cron_worker is None:
        return {"ok": True, "skipped": True}
    try:
        running = cron_worker.scheduler.running if hasattr(cron_worker, "scheduler") else False
        return {"ok": running}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _check_subagent_pool(subagent_pool: Any) -> dict[str, Any]:
    if subagent_pool is None:
        return {"ok": True, "skipped": True}
    try:
        # SubagentPool tem semaphore com capacidade configurável
        has_capacity = True
        if hasattr(subagent_pool, "_semaphore"):
            has_capacity = subagent_pool._semaphore._value > 0  # type: ignore[attr-defined]
        return {"ok": has_capacity}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Router factory ────────────────────────────────────────────────────────────

def make_health_router(
    get_db_pool: Any = None,
    get_cron_worker: Any = None,
    get_subagent_pool: Any = None,
) -> APIRouter:
    """Cria o router com os 3 health endpoints.

    Parâmetros são callables (lambdas) resolvidos em request-time,
    mesma convenção usada nos demais routers do projeto.
    Passando None os checks correspondentes retornam skipped=True.
    """
    def _pool() -> Any:
        return get_db_pool() if callable(get_db_pool) else None

    def _cron() -> Any:
        return get_cron_worker() if callable(get_cron_worker) else None

    def _pool_inst() -> Any:
        return get_subagent_pool() if callable(get_subagent_pool) else None

    router = APIRouter(prefix="/health", tags=["health"])

    @router.get("/live")
    async def liveness() -> JSONResponse:
        """Liveness probe: só responde 200. Não faz I/O. <50ms."""
        return JSONResponse({"status": "alive"})

    @router.get("/ready")
    async def readiness() -> JSONResponse:
        """Readiness probe: checa componentes críticos."""
        checks = await asyncio.gather(
            _check_sqlite(),
            _check_postgres(_pool()),
            return_exceptions=False,
        )
        sqlite_result = checks[0]
        postgres_result = checks[1]
        scheduler_result = _check_scheduler(_cron())
        pool_result = _check_subagent_pool(_pool_inst())

        all_ok = all(
            c.get("ok", False) for c in [
                sqlite_result, postgres_result, scheduler_result, pool_result
            ]
        )
        status_code = 200 if all_ok else 503
        return JSONResponse(
            {
                "status": "ready" if all_ok else "degraded",
                "checks": {
                    "sqlite": sqlite_result,
                    "postgres": postgres_result,
                    "scheduler": scheduler_result,
                    "subagent_pool": pool_result,
                },
            },
            status_code=status_code,
        )

    @router.get("/deep")
    async def deep_check() -> JSONResponse:
        """Deep probe: readiness + skill noop via exec_tool."""
        t0 = time.monotonic()

        # Roda checks de readiness e noop skill em paralelo
        ready_checks, noop_result = await asyncio.gather(
            _gather_ready_checks(_pool(), _cron(), _pool_inst()),
            _safe_noop(),
        )

        total_ms = int((time.monotonic() - t0) * 1000)
        all_ok = ready_checks["all_ok"] and noop_result.get("ok", False)

        return JSONResponse(
            {
                "status": "ok" if all_ok else "degraded",
                "total_duration_ms": total_ms,
                "checks": {
                    **ready_checks["checks"],
                    "noop_skill": noop_result,
                },
            },
            status_code=200 if all_ok else 503,
        )

    return router


async def _gather_ready_checks(
    db_pool: Any, cron_worker: Any, subagent_pool: Any
) -> dict[str, Any]:
    checks = await asyncio.gather(
        _check_sqlite(),
        _check_postgres(db_pool),
        return_exceptions=False,
    )
    scheduler_result = _check_scheduler(cron_worker)
    pool_result = _check_subagent_pool(subagent_pool)
    all_ok = all(
        c.get("ok", False) for c in [checks[0], checks[1], scheduler_result, pool_result]
    )
    return {
        "all_ok": all_ok,
        "checks": {
            "sqlite": checks[0],
            "postgres": checks[1],
            "scheduler": scheduler_result,
            "subagent_pool": pool_result,
        },
    }


async def _safe_noop() -> dict[str, Any]:
    try:
        return await _run_noop_skill()
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout (>2s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
