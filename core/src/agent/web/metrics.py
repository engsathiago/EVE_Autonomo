"""Métricas Prometheus para o Web UI (F11) — namespace agent_web_.

Usa registry separado para evitar conflitos com o registry padrão.
Integrado ao endpoint /metrics do server.py principal.
"""
from __future__ import annotations

import prometheus_client as prom

# Registry isolado da F11 — evita conflito com outros registries ou testes
_REGISTRY = prom.CollectorRegistry(auto_describe=True)

http_requests_total = prom.Counter(
    "agent_web_http_requests_total",
    "Total de requests HTTP ao web UI por path e status",
    ["path", "status"],
    registry=_REGISTRY,
)

http_request_duration_seconds = prom.Histogram(
    "agent_web_http_request_duration_seconds",
    "Duração de requests HTTP ao web UI",
    ["path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=_REGISTRY,
)

ws_connections_active = prom.Gauge(
    "agent_web_ws_connections_active",
    "Número de conexões WebSocket ativas",
    registry=_REGISTRY,
)

ws_messages_total = prom.Counter(
    "agent_web_ws_messages_total",
    "Total de mensagens WebSocket por tópico e direção",
    ["topic", "direction"],
    registry=_REGISTRY,
)

sessions_active = prom.Gauge(
    "agent_web_sessions_active",
    "Número de sessões web ativas",
    registry=_REGISTRY,
)

chat_messages_total = prom.Counter(
    "agent_web_chat_messages_total",
    "Total de mensagens de chat enviadas pelo painel web",
    registry=_REGISTRY,
)

chat_response_latency_seconds = prom.Histogram(
    "agent_web_chat_response_latency_seconds",
    "Latência da resposta do agente no chat web",
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=_REGISTRY,
)


def prometheus_text() -> str:
    """Exporta métricas F11 em formato Prometheus text."""
    return prom.generate_latest(_REGISTRY).decode("utf-8")
