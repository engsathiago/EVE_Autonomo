"""
Métricas Prometheus para deploy (F10).

Define as 12 séries do spec §5.3 usando prometheus_client.
O endpoint /metrics é registrado em health.py junto com os health checks.

Uso:
    from agent.deploy.metrics import METRICS, make_metrics_router
    app.include_router(make_metrics_router())
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil
import prometheus_client as prom
from fastapi import APIRouter
from fastapi.responses import Response

# ── Namespace e registry ──────────────────────────────────────────────────────
# Usa registry separado para evitar conflitos com o registry padrão do prometheus
# caso o processo seja importado em testes ou múltiplos contextos.
_REGISTRY = prom.CollectorRegistry(auto_describe=True)

_START_TIME = time.time()


@dataclass
class _Metrics:
    missions_total: prom.Counter
    mission_duration_seconds: prom.Histogram
    skills_executed_total: prom.Counter
    skill_execution_duration_seconds: prom.Histogram
    subagent_pool_active: prom.Gauge
    sandbox_executions_total: prom.Counter
    critic_decisions_total: prom.Counter
    scheduler_jobs_active: prom.Gauge
    worker_restarts_total: prom.Counter
    db_query_duration_seconds: prom.Histogram
    memory_bytes: prom.Gauge
    uptime_seconds: prom.Gauge


def _build_metrics() -> _Metrics:
    return _Metrics(
        missions_total=prom.Counter(
            "agent_missions_total",
            "Total de missões por status",
            ["status"],
            registry=_REGISTRY,
        ),
        mission_duration_seconds=prom.Histogram(
            "agent_mission_duration_seconds",
            "Duração de missões em segundos",
            registry=_REGISTRY,
        ),
        skills_executed_total=prom.Counter(
            "agent_skills_executed_total",
            "Total de execuções de skill por nome e resultado",
            ["skill", "result"],
            registry=_REGISTRY,
        ),
        skill_execution_duration_seconds=prom.Histogram(
            "agent_skill_execution_duration_seconds",
            "Duração de execução de skill em segundos",
            ["skill"],
            registry=_REGISTRY,
        ),
        subagent_pool_active=prom.Gauge(
            "agent_subagent_pool_active",
            "Número de subagentes ativos no momento",
            registry=_REGISTRY,
        ),
        sandbox_executions_total=prom.Counter(
            "agent_sandbox_executions_total",
            "Total de execuções em sandbox por perfil e resultado",
            ["profile", "result"],
            registry=_REGISTRY,
        ),
        critic_decisions_total=prom.Counter(
            "agent_critic_decisions_total",
            "Total de decisões do Crítico por veredicto",
            ["verdict"],
            registry=_REGISTRY,
        ),
        scheduler_jobs_active=prom.Gauge(
            "agent_scheduler_jobs_active",
            "Número de jobs ativos no APScheduler",
            registry=_REGISTRY,
        ),
        worker_restarts_total=prom.Counter(
            "agent_worker_restarts_total",
            "Total de restarts por worker (lido do worker_health)",
            ["worker"],
            registry=_REGISTRY,
        ),
        db_query_duration_seconds=prom.Histogram(
            "agent_db_query_duration_seconds",
            "Latência de queries por banco",
            ["db"],
            registry=_REGISTRY,
        ),
        memory_bytes=prom.Gauge(
            "agent_memory_bytes",
            "RSS do processo agente em bytes",
            registry=_REGISTRY,
        ),
        uptime_seconds=prom.Gauge(
            "agent_uptime_seconds",
            "Segundos desde o início do processo",
            registry=_REGISTRY,
        ),
    )


METRICS = _build_metrics()

# Inicializa counters com zero para que apareçam em /metrics logo no boot
for _status in ("completed", "failed", "cancelled"):
    METRICS.missions_total.labels(status=_status)
for _verdict in ("approve", "reject", "escalate"):
    METRICS.critic_decisions_total.labels(verdict=_verdict)
for _worker_name in ("orchestrator", "scheduler", "api", "heartbeat"):
    METRICS.worker_restarts_total.labels(worker=_worker_name)
for _result in ("ok", "killed", "timeout"):
    for _profile in ("default", "skill_dev", "untrusted"):
        METRICS.sandbox_executions_total.labels(profile=_profile, result=_result)


# ── Collector de métricas dinâmicas ──────────────────────────────────────────

def _update_dynamic_metrics() -> None:
    """Atualiza gauges que precisam de leitura pontual (não são incrementais)."""
    try:
        proc = psutil.Process(os.getpid())
        METRICS.memory_bytes.set(proc.memory_info().rss)
    except Exception:
        pass

    METRICS.uptime_seconds.set(time.time() - _START_TIME)

    # Lê restarts do worker_health (SQLite) para que o counter reflita o estado
    # real mesmo após restart do processo API.
    try:
        import sqlite3

        db_path = os.environ.get("AGENT_DB_SQLITE", "agent.db")
        conn = sqlite3.connect(db_path, timeout=1)
        rows = conn.execute(
            "SELECT worker, restarts FROM worker_health"
        ).fetchall()
        conn.close()
        for worker_name, restarts in rows:
            # Gauge não é o ideal aqui, mas Counter não aceita set().
            # Usamos a diferença para não recuar o counter:
            _sync_worker_restarts_counter(worker_name, restarts or 0)
    except Exception:
        pass


# Rastreia o valor já "incrementado" para evitar double-counting
_RESTART_SEEN: dict[str, int] = {}


def _sync_worker_restarts_counter(worker_name: str, total: int) -> None:
    seen = _RESTART_SEEN.get(worker_name, 0)
    delta = max(0, total - seen)
    if delta > 0:
        METRICS.worker_restarts_total.labels(worker=worker_name).inc(delta)
        _RESTART_SEEN[worker_name] = total


# ── Router FastAPI ────────────────────────────────────────────────────────────

def make_metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        _update_dynamic_metrics()
        data = prom.generate_latest(_REGISTRY)
        return Response(
            content=data,
            media_type=prom.CONTENT_TYPE_LATEST,
        )

    return router
