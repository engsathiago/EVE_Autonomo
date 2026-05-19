"""OrchestratorWorker: processo independente que monitora o orchestrator via Redis."""
from __future__ import annotations

import asyncio
import os

from agent.deploy.workers.base import Worker
from agent.observability.logger import get_logger

log = get_logger(__name__)

_POLL_INTERVAL_S = 10


class OrchestratorWorker(Worker):
    """Processo autônomo que representa o orchestrator no modelo de supervisão.

    Responsabilidades neste processo:
    - Monitorar a fila Redis `agent:orchestrator:heartbeat` publicada pelo server.
    - Publicar estado próprio para o supervisor detectar travamentos.
    - Em futura refatoração: rodar o Orchestrator diretamente sem o uvicorn.

    Por enquanto funciona como processo sentinel: se ele morrer, o Supervisor
    reinicia e emite `worker.restarted`. Isso valida C2 e C3 do spec.
    """

    name = "orchestrator"

    def __init__(self, redis_url: str = "redis://127.0.0.1:6379/0") -> None:
        super().__init__()
        self._redis_url = redis_url

    async def run(self) -> None:
        log.info("orchestrator_worker.starting", pid=os.getpid())
        try:
            import redis.asyncio as aioredis

            client = await aioredis.from_url(self._redis_url, decode_responses=True)
            try:
                while not self._stop_event.is_set():
                    try:
                        await client.ping()
                        await client.set(
                            "agent:orchestrator:last_seen",
                            str(asyncio.get_event_loop().time()),
                            ex=60,
                        )
                    except Exception as exc:
                        log.warning("orchestrator_worker.redis_error", error=str(exc))
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=_POLL_INTERVAL_S
                        )
                    except asyncio.TimeoutError:
                        pass
            finally:
                await client.aclose()
        except ImportError:
            # Redis não disponível — roda loop simples para o supervisor monitorar
            log.warning("orchestrator_worker.redis_unavailable")
            await self._stop_event.wait()

        log.info("orchestrator_worker.stopped", pid=os.getpid())
