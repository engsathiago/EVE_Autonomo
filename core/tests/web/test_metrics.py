"""Testa que métricas agent_web_ aparecem no registry F11."""
from __future__ import annotations

import pytest


def test_web_metrics_registered() -> None:
    """Todos os 7 counters/gauges/histograms agent_web_ devem estar no registry."""
    from agent.web import metrics as m

    # Verifica que as métricas foram criadas no registry correto
    registered_names = list(m._REGISTRY._names_to_collectors.keys())

    expected = [
        "agent_web_http_requests_total",
        "agent_web_http_request_duration_seconds",
        "agent_web_ws_connections_active",
        "agent_web_ws_messages_total",
        "agent_web_sessions_active",
        "agent_web_chat_messages_total",
        "agent_web_chat_response_latency_seconds",
    ]
    for name in expected:
        assert any(name in n for n in registered_names), (
            f"Métrica {name} não encontrada. Registradas: {registered_names}"
        )


def test_web_metrics_incrementable() -> None:
    """Métricas devem ser incrementáveis sem erros."""
    from agent.web import metrics as m
    m.http_requests_total.labels(path="/api/v1/test", status="200").inc()
    m.ws_connections_active.inc()
    m.ws_connections_active.dec()
    m.ws_messages_total.labels(topic="chat", direction="in").inc()
    m.chat_messages_total.inc()
    m.sessions_active.set(0)


def test_prometheus_text_output() -> None:
    """prometheus_text() deve retornar string não-vazia com linhas de métricas."""
    from agent.web.metrics import prometheus_text
    text = prometheus_text()
    assert "agent_web_" in text
    assert len(text) > 0
