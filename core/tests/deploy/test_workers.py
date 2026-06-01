"""Testes dos workers (F10)."""

from __future__ import annotations

import asyncio

import pytest

from agent.deploy.workers.base import Worker
from agent.deploy.workers.heartbeat_worker import HeartbeatWorker
from agent.deploy.workers.orchestrator_worker import OrchestratorWorker
from agent.deploy.workers.scheduler_worker import SchedulerWorker

# ── Worker ABC ────────────────────────────────────────────────────────────────


class _ConcreteWorker(Worker):
    name = "concrete"
    ran = False

    async def run(self) -> None:
        self.ran = True


class TestWorkerBase:
    def test_has_name(self) -> None:
        w = _ConcreteWorker()
        assert w.name == "concrete"

    @pytest.mark.asyncio
    async def test_run_called(self) -> None:
        w = _ConcreteWorker()
        await w.run()
        assert w.ran is True

    def test_request_stop_without_loop(self) -> None:
        w = _ConcreteWorker()
        # Fora de um event loop, request_stop() não deve levantar exceção
        w.request_stop()


# ── OrchestratorWorker ────────────────────────────────────────────────────────


class TestOrchestratorWorker:
    def test_name(self) -> None:
        w = OrchestratorWorker()
        assert w.name == "orchestrator"

    @pytest.mark.asyncio
    async def test_run_stops_when_event_set(self) -> None:
        w = OrchestratorWorker(redis_url="redis://nonexistent:9999/0")
        # run() deve terminar quando stop_event é setado
        task = asyncio.create_task(w.run())
        await asyncio.sleep(0.05)
        w._stop_event.set()
        await asyncio.wait_for(task, timeout=2.0)


# ── SchedulerWorker ───────────────────────────────────────────────────────────


class TestSchedulerWorker:
    def test_name(self) -> None:
        w = SchedulerWorker()
        assert w.name == "scheduler"

    @pytest.mark.asyncio
    async def test_run_stops_when_event_set(self) -> None:
        w = SchedulerWorker(redis_url="redis://nonexistent:9999/0")
        task = asyncio.create_task(w.run())
        await asyncio.sleep(0.05)
        w._stop_event.set()
        await asyncio.wait_for(task, timeout=2.0)


# ── HeartbeatWorker ───────────────────────────────────────────────────────────


class TestHeartbeatWorker:
    def test_name(self) -> None:
        w = HeartbeatWorker()
        assert w.name == "heartbeat"

    @pytest.mark.asyncio
    async def test_stops_after_max_failures(self) -> None:
        """Worker deve encerrar após MAX_FAILURES falhas consecutivas."""
        w = HeartbeatWorker(
            api_url="http://127.0.0.1:19999",  # porta inexistente
            check_interval_s=0.01,
        )
        # Com 5 falhas e interval=0.01, deve encerrar em < 1s
        await asyncio.wait_for(w.run(), timeout=3.0)

    @pytest.mark.asyncio
    async def test_stops_via_stop_event(self) -> None:
        """Worker para ao setar stop_event sem esperar falhas."""
        w = HeartbeatWorker(
            api_url="http://127.0.0.1:19999",
            check_interval_s=60,  # longo — stop_event deve ser mais rápido
        )
        task = asyncio.create_task(w.run())
        await asyncio.sleep(0.05)
        w._stop_event.set()
        await asyncio.wait_for(task, timeout=2.0)


# ── ApiWorker ─────────────────────────────────────────────────────────────────


class TestApiWorker:
    def test_name(self) -> None:
        from agent.deploy.workers.api_worker import ApiWorker

        w = ApiWorker()
        assert w.name == "api"

    def test_request_stop_sets_server_exit(self) -> None:
        from unittest.mock import MagicMock

        from agent.deploy.workers.api_worker import ApiWorker

        w = ApiWorker()
        mock_server = MagicMock()
        w._server = mock_server
        w.request_stop()
        assert mock_server.should_exit is True
