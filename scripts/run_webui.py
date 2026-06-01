"""Serve o Web UI localmente via FastAPI + uvicorn na porta 8080.

Uso:
    cd ~/Desktop/agent
    PYTHONPATH=core/src core/.venv312/bin/python scripts/run_webui.py

Abrir: http://localhost:8080/?token=<token impresso>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Host path para src do core
sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "src"))

import asyncpg
import uvicorn
from agent.observability.logger import get_logger
from agent.web.auth import generate_token, read_token, write_token
from agent.web.server import make_web_app

log = get_logger(__name__)

_PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
_PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
_PG_USER = os.getenv("POSTGRES_USER", "agent")
_PG_PASS = os.getenv("POSTGRES_PASSWORD", "qualquercoisa123")
_PG_DB = os.getenv("POSTGRES_DB", "agent")
_PORT = int(os.getenv("AGENT_WEB_PORT", "8080"))


def _ensure_token() -> str:
    tok = read_token()
    if not tok:
        tok = generate_token()
        write_token(tok)
        print(f"[webui] Token gerado e salvo em ~/.agent/web_token")
    return tok


app = make_web_app()


@app.on_event("startup")
async def _startup() -> None:
    pool = await asyncpg.create_pool(
        host=_PG_HOST,
        port=_PG_PORT,
        user=_PG_USER,
        password=_PG_PASS,
        database=_PG_DB,
        min_size=1,
        max_size=5,
        command_timeout=10,
    )
    from agent.missions.store import MissionStore
    from agent.tasks.store import TaskStore
    from agent.web.routes.api import configure

    configure(
        db_pool=pool,
        missions_store=MissionStore(pool),
        task_store=TaskStore(pool),
    )
    app.state.pool = pool
    log.info("webui.startup.ok", host=_PG_HOST, port=_PG_PORT)


@app.on_event("shutdown")
async def _shutdown() -> None:
    pool = getattr(app.state, "pool", None)
    if pool:
        await pool.close()
        log.info("webui.shutdown.pool_closed")


if __name__ == "__main__":
    tok = _ensure_token()
    print(f"[webui] http://localhost:{_PORT}/?token={tok}")
    uvicorn.run(app, host="0.0.0.0", port=_PORT, log_level="warning")
