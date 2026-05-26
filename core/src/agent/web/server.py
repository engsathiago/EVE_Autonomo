"""Web UI server (F11) — integrado ao processo principal via make_web_router().

Bind em 127.0.0.1:8080 (mesmo que o serviço principal, controlado pelo uvicorn).
CORS: só 'null' e 'http://127.0.0.1:8080'.
Rate limit in-memory: 60 req/s por endpoint.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from agent.observability.logger import get_logger
from agent.web import metrics as web_metrics
from agent.web.routes.api import configure as configure_api
from agent.web.routes.api import make_api_router
from agent.web.routes.static import make_static_router
from agent.web.routes.ws import make_ws_router

log = get_logger(__name__)

# ── Rate limiter in-memory ────────────────────────────────────────────────────
# 60 req/s por endpoint. WebSocket não entra aqui.
_RATE_LIMIT = 60
_RATE_WINDOW_S = 1.0
_rate_counters: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> bool:
    """Retorna True se dentro do limite, False se deve ser bloqueado."""
    now = time.monotonic()
    hits = _rate_counters[key]
    # Remove entradas fora da janela
    cutoff = now - _RATE_WINDOW_S
    _rate_counters[key] = [t for t in hits if t > cutoff]
    if len(_rate_counters[key]) >= _RATE_LIMIT:
        return False
    _rate_counters[key].append(now)
    return True


class _RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        # WebSocket e /api/v1/stream ficam fora do rate limit
        if path == "/api/v1/stream" or request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        key = path
        if not _check_rate_limit(key):
            return Response(
                content='{"detail":"Rate limit excedido"}',
                status_code=429,
                media_type="application/json",
            )
        return await call_next(request)


class _LogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        import uuid as _uuid

        request_id = str(_uuid.uuid4())[:8]
        t0 = time.monotonic()
        response = await call_next(request)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        path = request.url.path
        status = response.status_code

        log.info(
            "web.request",
            request_id=request_id,
            path=path,
            method=request.method,
            status=status,
            latency_ms=latency_ms,
        )
        web_metrics.http_requests_total.labels(path=path, status=str(status)).inc()
        web_metrics.http_request_duration_seconds.labels(path=path).observe(latency_ms / 1000)
        return response


def make_web_app(
    missions_store=None,
    missions_planner=None,
    missions_reflector=None,
    skill_manager=None,
    memory_store=None,
    task_store=None,
    db_pool=None,
    subagent_pool=None,
    approval_manager=None,
    orchestrator=None,
) -> FastAPI:
    """Cria aplicação FastAPI standalone para testes unitários."""
    app = FastAPI(title="agent-web", docs_url=None, redoc_url=None)
    _apply_middleware(app)
    _register_routes(
        app,
        missions_store=missions_store,
        missions_planner=missions_planner,
        missions_reflector=missions_reflector,
        skill_manager=skill_manager,
        memory_store=memory_store,
        task_store=task_store,
        db_pool=db_pool,
        subagent_pool=subagent_pool,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
    )
    return app


def attach_web_routes(
    app: FastAPI,
    missions_store=None,
    missions_planner=None,
    missions_reflector=None,
    skill_manager=None,
    memory_store=None,
    task_store=None,
    db_pool=None,
    subagent_pool=None,
    approval_manager=None,
    orchestrator=None,
) -> None:
    """Anexa rotas web à app FastAPI principal (server.py da F10)."""
    _apply_middleware(app)
    _register_routes(
        app,
        missions_store=missions_store,
        missions_planner=missions_planner,
        missions_reflector=missions_reflector,
        skill_manager=skill_manager,
        memory_store=memory_store,
        task_store=task_store,
        db_pool=db_pool,
        subagent_pool=subagent_pool,
        approval_manager=approval_manager,
        orchestrator=orchestrator,
    )


def _apply_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://127.0.0.1:8080"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-Agent-Token", "Content-Type"],
    )
    app.add_middleware(_RateLimitMiddleware)
    app.add_middleware(_LogMiddleware)


def _register_routes(app: FastAPI, **kwargs: Any) -> None:
    configure_api(**kwargs)
    app.include_router(make_api_router())
    app.include_router(
        make_ws_router(
            get_orchestrator=lambda: kwargs.get("orchestrator"),
            get_task_store=lambda: kwargs.get("task_store"),
        )
    )
    # Estático por último (catch-all)
    app.include_router(make_static_router())
