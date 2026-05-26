"""Adapter fino para o Crítico (F7)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    import asyncpg

log = get_logger(__name__)


async def get_critic_queue(
    db_pool: asyncpg.Pool, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Retorna avaliações pendentes (sem veredito final ainda)."""
    try:
        rows = await db_pool.fetch(
            """
            SELECT id, tool_name, tool_args, context_summary, tier,
                   estimated_cost_usd, affects_external_world,
                   technical_verdict, devils_verdict, final_verdict,
                   created_at, mission_id, task_id
            FROM critic_evaluations
            WHERE final_verdict IS NULL
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        log.error("web.adapter.critic.queue_error", error=str(exc))
        return []


async def get_critic_history(
    db_pool: asyncpg.Pool,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    try:
        rows = await db_pool.fetch(
            """
            SELECT id, tool_name, tool_args, context_summary, tier,
                   estimated_cost_usd, affects_external_world,
                   technical_verdict, devils_verdict, final_verdict,
                   created_at, mission_id, task_id
            FROM critic_evaluations
            WHERE final_verdict IS NOT NULL
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        log.error("web.adapter.critic.history_error", error=str(exc))
        return []


def _row_to_dict(row: Any) -> dict[str, Any]:
    import json

    return {
        "id": str(row["id"]),
        "tool_name": row["tool_name"],
        "tool_args": json.loads(row["tool_args"])
        if isinstance(row["tool_args"], str)
        else row["tool_args"],
        "context_summary": row["context_summary"],
        "tier": row["tier"],
        "estimated_cost_usd": float(row["estimated_cost_usd"] or 0),
        "affects_external_world": bool(row["affects_external_world"]),
        "technical_verdict": _parse_verdict(row["technical_verdict"]),
        "devils_verdict": _parse_verdict(row["devils_verdict"]),
        "final_verdict": _parse_verdict(row["final_verdict"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "mission_id": str(row["mission_id"]) if row["mission_id"] else None,
        "task_id": str(row["task_id"]) if row["task_id"] else None,
    }


def _parse_verdict(raw: Any) -> dict | None:
    if raw is None:
        return None
    import json

    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}
    return raw
