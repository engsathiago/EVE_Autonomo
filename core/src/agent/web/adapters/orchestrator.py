"""Adapter fino para o orchestrator (F6) — envia mensagem e devolve stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.orchestrator.router import Orchestrator
    from agent.tasks.store import TaskStore

log = get_logger(__name__)


async def send_message(
    orchestrator: Orchestrator,
    task_store: TaskStore,
    text: str,
    conversation_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Envia mensagem ao orchestrator e produz eventos de stream."""
    from agent.tasks.task import Task, TaskSource

    task = Task(content=text, source=TaskSource.API)
    await task_store.create(task)

    try:
        result = await orchestrator.route(task)
        yield {"type": "token", "data": result.final_text}
        yield {
            "type": "done",
            "data": {
                "iterations": result.iterations,
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "cost_usd": result.estimated_cost_usd,
                "duration_s": result.duration_s,
                "tier": task.tier,
                "conversation_id": conversation_id,
            },
        }
    except Exception as exc:
        log.error("web.adapter.orchestrator.send_error", error=str(exc))
        yield {"type": "error", "data": str(exc)}
