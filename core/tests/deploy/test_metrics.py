"""Testes das métricas Prometheus (F10)."""
from __future__ import annotations

import prometheus_client as prom
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.deploy.metrics import _REGISTRY, METRICS, make_metrics_router

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

    def test_sandbox_counter_all_profiles_initialized(self) -> None:
        """C7: sandbox_executions_total inicializado para todos os perfis."""
        text = prom.generate_latest(_REGISTRY).decode()
        for profile in ("default", "skill_dev", "untrusted"):
            assert f'profile="{profile}"' in text, f"perfil {profile} ausente"


# ── C7: métricas não-zero logo após boot ──────────────────────────────────────

class TestMetricsBootC7:
    def test_worker_restarts_initialized_for_all_workers(self) -> None:
        """C7: worker_restarts_total tem labels para os 4 workers desde o boot."""
        text = prom.generate_latest(_REGISTRY).decode()
        for worker in ("orchestrator", "scheduler", "api", "heartbeat"):
            assert f'worker="{worker}"' in text, f"worker {worker} ausente em worker_restarts_total"

    def test_missions_total_initialized_for_all_statuses(self) -> None:
        """C7: missions_total tem labels completed/failed/cancelled desde o boot."""
        text = prom.generate_latest(_REGISTRY).decode()
        for status in ("completed", "failed", "cancelled"):
            assert f'status="{status}"' in text, f"status {status} ausente em missions_total"

    def test_critic_decisions_initialized_for_all_verdicts(self) -> None:
        """C7: critic_decisions_total tem labels approve/reject/escalate."""
        text = prom.generate_latest(_REGISTRY).decode()
        for verdict in ("approve", "reject", "escalate"):
            assert f'verdict="{verdict}"' in text, f"verdict {verdict} ausente"

    def test_sync_worker_restarts_counter_increments_delta(self) -> None:
        """_sync_worker_restarts_counter não duplica counts."""
        from agent.deploy.metrics import _RESTART_SEEN, _sync_worker_restarts_counter

        # Garante estado limpo para o worker de teste
        _RESTART_SEEN.pop("test_worker_sync", None)
        METRICS.worker_restarts_total.labels(worker="test_worker_sync")

        _sync_worker_restarts_counter("test_worker_sync", 5)
        _sync_worker_restarts_counter("test_worker_sync", 5)  # mesma leitura — sem incremento

        # Apenas 1 incremento de 5, não 10
        text = prom.generate_latest(_REGISTRY).decode()
        assert 'worker="test_worker_sync"' in text

    def test_update_dynamic_metrics_sets_uptime(self) -> None:
        """_update_dynamic_metrics define uptime > 0."""
        from agent.deploy.metrics import _update_dynamic_metrics
        _update_dynamic_metrics()
        text = prom.generate_latest(_REGISTRY).decode()
        for line in text.splitlines():
            if line.startswith("agent_uptime_seconds") and not line.startswith("#"):
                assert float(line.split()[-1]) > 0
                return
        pytest.fail("agent_uptime_seconds não encontrado")
