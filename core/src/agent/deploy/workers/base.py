"""Worker ABC: interface comum para os 4 workers do supervisor."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class Worker(ABC):
    """Contrato de um worker gerenciado pelo Supervisor.

    Cada worker roda em seu próprio processo (fork no POSIX,
    multiprocessing.Process no Windows). O Supervisor:
      - Chama `asyncio.run(worker.run())` no processo filho.
      - Monitora o PID filho para detectar crashes.
      - Chama `worker.request_stop()` antes de SIGTERM para graceful shutdown.

    Diferença POSIX vs Windows:
      - POSIX (Linux/macOS): `os.fork()` clona o processo pai;
        o filho herda descritores de arquivo, mas deve reinicializar
        event loops e conexões assíncronas (asyncpg, redis, etc.).
      - Windows: `multiprocessing.Process` usa `spawn`, que importa
        o módulo do zero sem herança de estado; o worker deve ser
        serializável via pickle (sem lambdas ou closures complexas).
    """

    #: Nome curto usado em logs, métricas e worker_health.
    name: str = "worker"

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()

    @abstractmethod
    async def run(self) -> None:
        """Ponto de entrada no processo filho. Roda até parar."""
        ...

    def request_stop(self) -> None:
        """Sinaliza parada ao loop do worker (thread-safe via loop.call_soon_threadsafe)."""
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(self._stop_event.set)
        except RuntimeError:
            # Sem event loop ativo — ignora (processo pode já estar encerrando)
            pass
