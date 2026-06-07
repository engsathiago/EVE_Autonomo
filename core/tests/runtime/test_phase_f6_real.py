"""
C.2 — Runtime validation Fase 6 (Cron + Subagentes)

Valida persistência end-to-end em cron_jobs e subagent_runs:
  - CronStore.create()  → linha em cron_jobs
  - TaskStore.create() × 2 + record_subagent_run() → linha em subagent_runs

Não usa LLM: valida o caminho de DB, não execução real do CronWorker.
O CronWorker + AIAgent requerem LLM para executar tasks — isso fica para
validação com OLLAMA_CLOUD_API_KEY disponível.

Requer: Postgres em localhost:5432.
Rodar com: pytest -m runtime tests/runtime/test_phase_f6_real.py -v
"""
from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from agent.scheduler.store import CronStore
from agent.tasks.store import TaskStore
from agent.tasks.task import Task, TaskSource

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_EVIDENCE_DIR = Path(__file__).parent / "evidence"

pytestmark = pytest.mark.runtime


@pytest.fixture
async def pg_pool():
    try:
        pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    except Exception as exc:
        pytest.skip(f"Postgres indisponível em localhost:5432: {exc}")
    yield pool
    await pool.close()


async def test_cron_job_persists_to_postgres(pg_pool):
    """CronStore.create() → linha em cron_jobs com campos corretos."""
    store = CronStore(pool=pg_pool)

    job = await store.create(
        name="rt-test-c2-cron",
        cron_expr="0 3 * * *",
        task_tpl="echo runtime-test",
        source="api",
        nl_original="todo dia às 3h",
    )

    row = await pg_pool.fetchrow("SELECT * FROM cron_jobs WHERE id = $1", job.id)
    assert row is not None, f"Linha {job.id} não encontrada em cron_jobs"
    assert row["name"] == "rt-test-c2-cron"
    assert row["cron_expr"] == "0 3 * * *"
    assert row["source"] == "api"
    assert row["enabled"] is True

    count = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM cron_jobs WHERE id = $1", job.id
    )
    assert count >= 1

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (_EVIDENCE_DIR / "f6_cron_job_id.txt").write_text(
        f"cron_job_id={job.id}\nname=rt-test-c2-cron\ncron_expr=0 3 * * *\n"
    )


async def test_subagent_run_persists_to_postgres(pg_pool):
    """TaskStore.create() × 2 + record_subagent_run() → linha em subagent_runs."""
    task_store = TaskStore(pool=pg_pool)

    # Cria task pai (simula trigger de cron/telegram)
    parent = Task(content="rt-test-c2 parent task", source=TaskSource.CRON)
    await task_store.create(parent)

    # Cria task filho (subagente)
    child = Task(
        content="rt-test-c2 child subagent",
        source=TaskSource.SUBAGENT,
        parent_id=parent.id,
    )
    await task_store.create(child)

    # Registra execução do subagente
    await task_store.record_subagent_run(
        task_id=child.id,
        parent_task=parent.id,
        tools_used=["echo", "list_dir"],
        duration_ms=142,
        success=True,
        summary="Runtime test C.2 — subagent executou sem LLM",
        raw_trace={"steps": 1, "test": True},
        verdict="success",
    )

    count = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM subagent_runs WHERE task_id = $1", child.id
    )
    assert count >= 1, f"Linha com task_id={child.id} não encontrada em subagent_runs"

    row = await pg_pool.fetchrow(
        "SELECT * FROM subagent_runs WHERE task_id = $1", child.id
    )
    assert row is not None
    assert row["success"] is True
    assert row["verdict"] == "success"
    assert row["duration_ms"] == 142

    (_EVIDENCE_DIR / "f6_cron_job_id.txt").write_text(
        (_EVIDENCE_DIR / "f6_cron_job_id.txt").read_text()
        + f"subagent_run_task_id={child.id}\nparent_task_id={parent.id}\n"
    )
