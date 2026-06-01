"""Testes de métricas Prometheus dos canais (C12)."""
from __future__ import annotations


def test_all_channel_metrics_exported():
    """C12: todos os agent_channel_* estão no prometheus_text."""
    from agent.channels.metrics import prometheus_text

    text = prometheus_text()

    expected_metrics = [
        "agent_channel_messages_total",
        "agent_channel_message_latency_seconds",
        "agent_channel_rate_limited_total",
        "agent_channel_unauthorized_total",
        "agent_channel_connection_status",
        "agent_channel_missions_dispatched_total",
    ]
    for metric in expected_metrics:
        assert metric in text, f"Métrica ausente: {metric}"


def test_messages_total_counter_increments():
    """Counter de mensagens incrementa corretamente."""
    from agent.channels import metrics as ch_metrics

    before = ch_metrics.messages_total.labels(channel="test", direction="in")._value.get()
    ch_metrics.messages_total.labels(channel="test", direction="in").inc()
    after = ch_metrics.messages_total.labels(channel="test", direction="in")._value.get()

    assert after == before + 1


def test_unauthorized_total_counter_increments():
    """Counter de não-autorizados incrementa."""
    from agent.channels import metrics as ch_metrics

    before = ch_metrics.unauthorized_total.labels(channel="test_unauth")._value.get()
    ch_metrics.unauthorized_total.labels(channel="test_unauth").inc()
    after = ch_metrics.unauthorized_total.labels(channel="test_unauth")._value.get()

    assert after == before + 1


def test_connection_status_gauge_settable():
    """Gauge de status de conexão pode ser 0 ou 1."""
    from agent.channels import metrics as ch_metrics

    ch_metrics.connection_status.labels(channel="testchan").set(1)
    assert ch_metrics.connection_status.labels(channel="testchan")._value.get() == 1

    ch_metrics.connection_status.labels(channel="testchan").set(0)
    assert ch_metrics.connection_status.labels(channel="testchan")._value.get() == 0


def test_rate_limited_counter_has_reason_label():
    """Counter de rate limit tem label 'reason'."""
    from agent.channels import metrics as ch_metrics

    ch_metrics.rate_limited_total.labels(channel="rc", reason="user").inc()
    ch_metrics.rate_limited_total.labels(channel="rc", reason="channel").inc()
    # Não deve levantar exceção
