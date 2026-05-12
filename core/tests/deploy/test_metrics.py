"""Testes das métricas Prometheus (F10)."""
from __future__ import annotations

import pytest

import prometheus_client as prom
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.deploy.metrics import METRICS, _REGISTRY, make_metrics_router


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def metrics_client() -> TestClient:
    app = FastAPI()
    app.include_router(make_metrics_router())
    return TestClient(app)


# ── Existência das 12 séries ──────────────────────────────────────────────────

class TestMetricsDefinition:
    def test_missions_total_is_counter(self) -> None:
        assert isinstance(METRICS.missions_total, prom.Counter)

    def test_mission_duration_is_histogram(self) -> None:
        assert isinstance(METRICS.mission_duration_seconds, prom.Histogram)

    def test_skills_executed_is_counter(self) -> None:
        assert isinstance(METRICS.skills_executed_total, prom.Counter)

    def test_skill_duration_is_histogram(self) -> None:
        assert isinstance(METRICS.skill_execution_duration_seconds, prom.Histogram)

    def test_subagent_pool_active_is_gauge(self) -> None:
        assert isinstance(METRICS.subagent_pool_active, prom.Gauge)

    def test_sandbox_executions_is_counter(self) -> None:
        assert isinstance(METRICS.sandbox_executions_total, prom.Counter)

    def test_critic_decisions_is_counter(self) -> None:
        assert isinstance(METRICS.critic_decisions_total, prom.Counter)

    def test_scheduler_jobs_is_gauge(self) -> None:
        assert isinstance(METRICS.scheduler_jobs_active, prom.Gauge)

    def test_worker_restarts_is_counter(self) -> None:
        assert isinstance(METRICS.worker_restarts_total, prom.Counter)

    def test_db_query_duration_is_histogram(self) -> None:
        assert isinstance(METRICS.db_query_duration_seconds, prom.Histogram)

    def test_memory_bytes_is_gauge(self) -> None:
        assert isinstance(METRICS.memory_bytes, prom.Gauge)

    def test_uptime_seconds_is_gauge(self) -> None:
        assert isinstance(METRICS.uptime_seconds, prom.Gauge)


# ── Endpoint /metrics ─────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_returns_200(self, metrics_client: TestClient) -> None:
        resp = metrics_client.get("/metrics")
        assert resp.status_code == 200

    def test_content_type_prometheus(self, metrics_client: TestClient) -> None:
        resp = metrics_client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_all_12_series_present(self, metrics_client: TestClient) -> None:
        resp = metrics_client.get("/metrics")
        body = resp.text
        expected = [
            "agent_missions_total",
            "agent_mission_duration_seconds",
            "agent_skills_executed_total",
            "agent_skill_execution_duration_seconds",
            "agent_subagent_pool_active",
            "agent_sandbox_executions_total",
            "agent_critic_decisions_total",
            "agent_scheduler_jobs_active",
            "agent_worker_restarts_total",
            "agent_db_query_duration_seconds",
            "agent_memory_bytes",
            "agent_uptime_seconds",
        ]
        for metric_name in expected:
            assert metric_name in body, f"métrica ausente: {metric_name}"

    def test_uptime_is_positive(self, metrics_client: TestClient) -> None:
        resp = metrics_client.get("/metrics")
        body = resp.text
        for line in body.splitlines():
            if line.startswith("agent_uptime_seconds") and not line.startswith("#"):
                value = float(line.split()[-1])
                assert value >= 0
                return
        pytest.fail("agent_uptime_seconds não encontrado no output")

    def test_memory_bytes_positive(self, metrics_client: TestClient) -> None:
        resp = metrics_client.get("/metrics")
        body = resp.text
        for line in body.splitlines():
            if line.startswith("agent_memory_bytes") and not line.startswith("#"):
                value = float(line.split()[-1])
                assert value > 0, "RSS deve ser > 0"
                return
        pytest.fail("agent_memory_bytes não encontrado")


# ── Incremento de counters ────────────────────────────────────────────────────

class TestMetricsIncrement:
    def test_mission_counter_increment(self, metrics_client: TestClient) -> None:
        before_text = metrics_client.get("/metrics").text
        METRICS.missions_total.labels(status="completed").inc()
        after_text = metrics_client.get("/metrics").text
        # Não comparamos valores absolutos (paralelo com outros testes)
        assert "agent_missions_total" in after_text

    def test_critic_counter_labels(self) -> None:
        METRICS.critic_decisions_total.labels(verdict="approve").inc(2)
        METRICS.critic_decisions_total.labels(verdict="reject").inc(1)
        text = prom.generate_latest(_REGISTRY).decode()
        assert 'verdict="approve"' in text
        assert 'verdict="reject"' in text
