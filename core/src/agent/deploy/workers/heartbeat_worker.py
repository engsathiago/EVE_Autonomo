"""HeartbeatWorker: verifica saúde do agente via /health/ready a cada 30s."""
from __future__ import annotations

import asyncio
import os

from agent.deploy.workers.base import Worker
from agent.observability.logger import get_logger

log = get_logger(__name__)

_CHECK_INTERVAL_S = 30
_HTTP_TIMEOUT_S = 10


class HeartbeatWorker(Worker):
    """Processo que faz health check periódico e loga resultado.

    Diferente dos outros workers, este não representa um componente de negócio.
    Ele verifica que a API está respondendo e loga métricas de disponibilidade.

    O sd_notify WATCHDOG=1 é enviado pelo Supervisor diretamente (pois o systemd
    com NotifyAccess=main só aceita notificações do processo principal). Este
    worker é o "canário" — se não conseguir chegar na API por N ciclos
    consecutivos, ele encerra com exit_code=1 para o Supervisor reiniciar tudo.
    """

    name = "heartbeat"
    _MAX_FAILURES = 5

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8000",
        check_interval_s: float = _CHECK_INTERVAL_S,
    ) -> None:
        super().__init__()
        self._api_url = api_url
        self._check_interval_s = check_interval_s

    async def run(self) -> None:
        log.info("heartbeat_worker.starting", pid=os.getpid(), api=self._api_url)
        consecutive_failures = 0

        try:
            import httpx
        except ImportError:
            log.error("heartbeat_worker.httpx_missing")
            return

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            while not self._stop_event.is_set():
                try:
                    resp = await client.get(f"{self._api_url}/health/ready")
                    if resp.status_code == 200:
                        consecutive_failures = 0
                        log.info("heartbeat_worker.ok", status=resp.status_code)
                    else:
                        consecutive_failures += 1
                        log.warning(
                            "heartbeat_worker.degraded",
                            status=resp.status_code,
                            failures=consecutive_failures,
                        )
                except Exception as exc:
                    consecutive_failures += 1
                    log.warning(
                        "heartbeat_worker.unreachable",
                        error=str(exc),
                        failures=consecutive_failures,
                    )

                if consecutive_failures >= self._MAX_FAILURES:
                    log.error(
                        "heartbeat_worker.giving_up",
                        failures=consecutive_failures,
                        msg="API inalcançável — encerrando para forçar restart do supervisor",
                    )
                    return  # exit_code=0; Supervisor detecta saída inesperada e reinicia

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._check_interval_s
                    )
                except asyncio.TimeoutError:
                    pass

        log.info("heartbeat_worker.stopped", pid=os.getpid())
