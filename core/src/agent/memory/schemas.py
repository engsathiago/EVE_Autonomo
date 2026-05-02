from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryKind = Literal["fact", "preference", "summary", "decision", "note"]


class MemoryEntry(BaseModel):
    id: UUID | None = None
    conversation_id: UUID | None = None
    kind: MemoryKind = "fact"
    content: str
    importance: int = Field(default=5, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    score: float | None = None


class CuratorDecision(BaseModel):
    persist: bool
    reason: str
    importance: int = Field(default=5, ge=1, le=10)
    kind: MemoryKind = "fact"
    extracted_content: str | None = None


class SearchResult(BaseModel):
    entries: list[MemoryEntry]
    query: str
    method: Literal["vector", "fts", "hybrid"]
