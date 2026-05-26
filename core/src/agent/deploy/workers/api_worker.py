"""ApiWorker: roda o servidor uvicorn/FastAPI com todos os componentes F0-F9."""

from __future__ import annotations

import os

from agent.deploy.workers.base import Worker
from agent.observability.logger import get_logger

log = get_logger(__name__)


class ApiWorker(Worker):
    """Inicia o servidor HTTP (uvicorn) com a aplicação FastAPI completa.

    Este é o worker "pesado": contém o lifespan completo (memória, orchestrator,
    scheduler, skills, etc.) inicializado dentro do mesmo processo uvicorn.
    Os outros workers (orchestrator, scheduler) são processos independentes que
    monitoram o estado via Redis/HTTP — arquitetura que permite evolução futura
    para processos verdadeiramente separados sem mudar a interface do Supervisor.
    """

    name = "api"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        log_level: str = "info",
    ) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._log_level = log_level
        self._server = None

    async def run(self) -> None:
        import uvicorn  # importado aqui para evitar import cíclico no supervisor

        from agent.server import app

        config = uvicorn.Config(
            app,
            host=self._host,
            port=self._port,
            log_level=self._log_level,
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        log.info("api_worker.starting", host=self._host, port=self._port, pid=os.getpid())
        await self._server.serve()
        log.info("api_worker.stopped", pid=os.getpid())

    def request_stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        super().request_stop()
