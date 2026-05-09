from __future__ import annotations

import asyncio

from agent.approvals.manager import ApprovalManager
from agent.observability.logger import get_logger

log = get_logger(__name__)

_INTERVAL_S = 60


class ApprovalScheduler:
    """Cron simples que expira approvals pendentes a cada 60s."""

    def __init__(self, manager: ApprovalManager, interval_s: int = _INTERVAL_S) -> None:
        self._manager = manager
        self._interval_s = interval_s
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="approval-scheduler")
            log.info("approval.scheduler.started", interval_s=self._interval_s)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("approval.scheduler.stopped")

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                await self._manager.expire_stale()
            except Exception:
                log.exception("approval.scheduler.error")
