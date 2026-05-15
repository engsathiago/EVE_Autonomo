"""Adapter fino para memória vetorial (F2 + F9)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.memory.store import MemoryStore

log = get_logger(__name__)


async def search_memory(
    store: "MemoryStore",
    query: str,
    k: int = 10,
    filter_kind: str | None = None,
) -> list[dict[str, Any]]:
    try:
        results = await store.search_hybrid(query, limit=k)
        out = []
        for entry, score in results:
            if filter_kind and entry.kind.value != filter_kind:
                continue
            out.append({
                "id": str(entry.id),
                "content": entry.content,
                "kind": entry.kind.value,
                "similarity": round(float(score), 4),
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "tags": entry.tags,
            })
        return out
    except Exception as exc:
        log.error("web.adapter.memory.search_error", error=str(exc))
        return []
