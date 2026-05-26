"""
CronWorker: wraps AsyncIOScheduler do APScheduler.

Design:
- Recebe o scheduler pronto (injeção) → testável com MemoryJobStore
- Cada cron_job registrado vira um APScheduler job com id=str(cron_job.id)
- Ao disparar, cria Task e delega ao Orchestrator
- Sobrevive a restart: jobs persistem em Postgres via SQLAlchemyJobStore

Note: APScheduler serializa o callable via pickle. Bound methods que contêm
o scheduler falham. Usamos _dispatch_cron_job (função de módulo) + _WORKER_REGISTRY
para evitar que o scheduler seja serializado.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from agent.observability.logger import get_logger
from agent.scheduler.parser import next_runs
from agent.scheduler.store import CronJob, CronStore
from agent.tasks.task import Task, TaskSource

if TYPE_CHECKING:
    from agent.orchestrator.router import Orchestrator
    from agent.scheduler.store import CronStore
    from agent.tasks.store import TaskStore

log = get_logger(__name__)

# Registry global: id(worker) → CronWorker — permite que _dispatch_cron_job
# (função de módulo, serializável) encontre o worker correto em runtime.
_WORKER_REGISTRY: dict[int, CronWorker] = {}


async def _dispatch_cron_job(worker_id: int, job_id_str: str) -> None:
    """Callable de módulo que o APScheduler pode serializar via pickle."""
    worker = _WORKER_REGISTRY.get(worker_id)
    if worker is None:
        return
    await worker._fire(UUID(job_id_str))


class CronWorker:
    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        cron_store: CronStore,
        task_store: TaskStore,
        orchestrator: Orchestrator,
        timezone: str = "America/Sao_Paulo",
    ) -> None:
        self._scheduler = scheduler
        self._cron_store = cron_store
        self._task_store = task_store
        self._orchestrator = orchestrator
        self._tz = timezone
        self._worker_id = id(self)
        _WORKER_REGISTRY[self._worker_id] = self

    async def start(self) -> None:
        """Carrega jobs habilitados do banco e inicia o scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()

        jobs = await self._cron_store.list(enabled_only=True)
        for job in jobs:
            self._register(job)

        log.info("cron.worker.started", jobs_loaded=len(jobs))

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
        _WORKER_REGISTRY.pop(self._worker_id, None)
        log.info("cron.worker.stopped")

    async def add_job(self, job: CronJob) -> None:
        self._register(job)
        log.info("cron.job.added", job_id=str(job.id), expr=job.cron_expr)

    def remove_job(self, job_id: UUID) -> None:
        try:
            self._scheduler.remove_job(str(job_id))
        except Exception:
            pass

    def _register(self, job: CronJob) -> None:
        job_id_str = str(job.id)

        # Remove job anterior se já existir (idempotente)
        try:
            self._scheduler.remove_job(job_id_str)
        except Exception:
            pass

        self._scheduler.add_job(
            _dispatch_cron_job,
            trigger=CronTrigger.from_crontab(job.cron_expr, timezone=self._tz),
            id=job_id_str,
            args=[self._worker_id, job_id_str],
            replace_existing=True,
            misfire_grace_time=60,
            max_instances=3,
            coalesce=True,
        )

    async def _fire(self, job_id: UUID) -> None:
        """Callback chamado pelo APScheduler quando um job dispara."""
        job = await self._cron_store.get(job_id)
        if job is None or not job.enabled:
            return

        log.info("cron.triggered", job_id=str(job_id), name=job.name)

        task = Task(
            content=job.task_tpl,
            source=TaskSource.CRON,
            cron_job_id=job_id,
            channel_target=job.target,
            channel_ref={"source": job.source, "target": job.target},
        )
        await self._task_store.create(task)

        fired_at = datetime.now(tz=UTC)
        last_status = "ok"
        last_error = None

        try:
            await self._orchestrator.route(task)
        except Exception as exc:
            last_status = "failed"
            last_error = str(exc)
            log.error("cron.job.failed", job_id=str(job_id), error=str(exc))
        finally:
            nexts = next_runs(job.cron_expr, n=1)
            next_run = nexts[0] if nexts else None
            await self._cron_store.update_run(
                job_id,
                last_run=fired_at,
                next_run=next_run,
                last_status=last_status,
                last_error=last_error,
            )
            log.info(
                "cron.completed",
                job_id=str(job_id),
                status=last_status,
                next_run=str(next_run),
            )
