"""SchedulerWorker: processo independente que mantém o APScheduler ativo."""
from __future__ import annotations

import asyncio
import os

from agent.deploy.workers.base import Worker
from agent.observability.logger import get_logger

log = get_logger(__name__)

_POLL_INTERVAL_S = 15


class SchedulerWorker(Worker):
    """Processo autônomo que representa o scheduler no modelo de supervisão.

    Responsabilidades neste processo:
    - Publicar `agent:scheduler:last_seen` no Redis para liveness check.
    - Em futura refatoração: rodar CronWorker diretamente aqui.

    Mesmo padrão do OrchestratorWorker: processo real que pode ser
    `kill -9`'d e reiniciado pelo Supervisor para validar C2/C3.
    """

    name = "scheduler"

    def __init__(self, redis_url: str = "redis://127.0.0.1:6379/0") -> None:
        super().__init__()
        self._redis_url = redis_url

    async def run(self) -> None:
        log.info("scheduler_worker.starting", pid=os.getpid())
        try:
            import redis.asyncio as aioredis

            client = await aioredis.from_url(self._redis_url, decode_responses=True)
            try:
                while not self._stop_event.is_set():
                    try:
                        await client.ping()
                        await client.set(
                            "agent:scheduler:last_seen",
                            str(asyncio.get_event_loop().time()),
                            ex=60,
                        )
                    except Exception as exc:
                        log.warning("scheduler_worker.redis_error", error=str(exc))
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=_POLL_INTERVAL_S
                        )
                    except asyncio.TimeoutError:
                        pass
            finally:
                await client.aclose()
        except ImportError:
            log.warning("scheduler_worker.redis_unavailable")
            await self._stop_event.wait()

        log.info("scheduler_worker.stopped", pid=os.getpid())
