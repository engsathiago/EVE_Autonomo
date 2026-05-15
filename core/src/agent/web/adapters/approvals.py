"""Adapter fino para aprovações pendentes (F5)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager

log = get_logger(__name__)


async def list_pending(manager: "ApprovalManager", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    try:
        rows = await manager.list_pending(limit=limit + offset)
        result = []
        for r in rows[offset:offset + limit]:
            result.append({
                "id": str(r.id),
                "tool_name": r.tool_name,
                "tool_args": r.tool_args,
                "context": r.context,
                "channel_ref": r.channel_ref,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            })
        return result
    except Exception as exc:
        log.error("web.adapter.approvals.list_error", error=str(exc))
        return []


async def decide_approval(
    manager: "ApprovalManager",
    approval_id: str,
    decision: str,
    note: str | None = None,
) -> bool:
    """Dispara o mesmo handler de decisão que o Telegram usa (C6).

    Chama manager.decide() — mesmo método usado pelo canal Telegram.
    """
    try:
        decision_val = "approve" if decision == "approve" else "reject"
        decided_by = f"web:{note}" if note else "web"
        await manager.decide(approval_id, decision=decision_val, decided_by=decided_by)
        return True
    except Exception as exc:
        log.error("web.adapter.approvals.decide_error", error=str(exc), approval_id=approval_id)
        return False
