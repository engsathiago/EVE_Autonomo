"""Métricas Prometheus para canais extras (F12) — namespace agent_channel_.

Registry isolado para não conflitar com F7/F11.
Integrado ao /metrics do server.py principal.
"""
from __future__ import annotations

import prometheus_client as prom

_REGISTRY = prom.CollectorRegistry(auto_describe=True)

messages_total = prom.Counter(
    "agent_channel_messages_total",
    "Total de mensagens por canal e direção",
    ["channel", "direction"],
    registry=_REGISTRY,
)

message_latency_seconds = prom.Histogram(
    "agent_channel_message_latency_seconds",
    "Latência de processamento de mensagem por canal",
    ["channel", "direction"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=_REGISTRY,
)

rate_limited_total = prom.Counter(
    "agent_channel_rate_limited_total",
    "Mensagens bloqueadas por rate limit",
    ["channel", "reason"],
    registry=_REGISTRY,
)

unauthorized_total = prom.Counter(
    "agent_channel_unauthorized_total",
    "Tentativas de acesso por usuário não autorizado",
    ["channel"],
    registry=_REGISTRY,
)

connection_status = prom.Gauge(
    "agent_channel_connection_status",
    "Status de conexão do canal (0=down, 1=up)",
    ["channel"],
    registry=_REGISTRY,
)

missions_dispatched_total = prom.Counter(
    "agent_channel_missions_dispatched_total",
    "Total de missões/tarefas despachadas por canal",
    ["channel"],
    registry=_REGISTRY,
)


def prometheus_text() -> str:
    """Exporta métricas F12 em formato Prometheus text."""
    return prom.generate_latest(_REGISTRY).decode("utf-8")
