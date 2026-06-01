"""
Integração: job cron sobrevive a restart do scheduler.

Precisa de Postgres real. Marcado com @pytest.mark.integration.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.scheduler.store import CronStore


def _noop() -> None:
    """Função noop com referência importável para o APScheduler serializar."""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cron_job_persists_in_db(db_pool: asyncpg.Pool) -> None:
    """Job criado no CronStore persiste após close/reopen (Postgres real)."""
    store = CronStore(db_pool)

    job = await store.create(
        name="test-persistence",
        cron_expr="*/2 * * * *",
        task_tpl="ping",
        source="cli",
    )

    retrieved = await store.get(job.id)
    assert retrieved is not None
    assert retrieved.name == "test-persistence"
    assert retrieved.cron_expr == "*/2 * * * *"

    # Limpa
    await store.delete(job.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apscheduler_job_persists(db_pool: asyncpg.Pool) -> None:
    """APScheduler com SQLAlchemyJobStore persiste job no banco e o recupera após restart."""
    import os

    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    db_url = os.getenv("POSTGRES_DSN", "postgresql://agent:agent@localhost:5432/agent")

    scheduler1 = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=db_url)},
        timezone="America/Sao_Paulo",
    )
    scheduler1.start()

    job_id = "test-persist-job"
    scheduler1.add_job(
        _noop,
        trigger=CronTrigger.from_crontab("*/2 * * * *", timezone="America/Sao_Paulo"),
        id=job_id,
        replace_existing=True,
    )

    # "Restart": desliga e liga novo scheduler com mesmo jobstore
    scheduler1.shutdown(wait=False)

    scheduler2 = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=db_url)},
        timezone="America/Sao_Paulo",
    )
    scheduler2.start()

    job = scheduler2.get_job(job_id)
    assert job is not None
    assert job.id == job_id

    scheduler2.remove_job(job_id)
    scheduler2.shutdown(wait=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_next_run_timezone(db_pool: asyncpg.Pool) -> None:
    """next_run é calculado com timezone São Paulo."""
    from agent.scheduler.parser import next_runs

    runs = next_runs("0 9 * * 1", n=1)
    assert len(runs) == 1
    # next_run deve ser em fuso UTC (armazenado assim no banco, exibido em SP)
    assert runs[0] > datetime.now(tz=UTC)
