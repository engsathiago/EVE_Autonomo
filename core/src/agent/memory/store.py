"""
MemoryStore: persistência e recuperação híbrida (vetorial + FTS) via asyncpg.
"""
from __future__ import annotations

import json
import os
from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector

from agent.memory.embeddings import embed as async_embed
from agent.memory.schemas import MemoryEntry, MemoryKind, SearchResult
from agent.observability.logger import get_logger

log = get_logger(__name__)

DEFAULT_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://agent:agent@postgres:5432/agent",
)


class MemoryStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, dsn: str = DEFAULT_DSN,
                     min_size: int = 2, max_size: int = 10) -> "MemoryStore":
        pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
        )
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    # -------------------------------------------------------------------------
    # Conversations / Messages
    # -------------------------------------------------------------------------

    async def create_conversation(
        self,
        title: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> UUID:
        row = await self._pool.fetchrow(
            """
            INSERT INTO conversations (title, user_id, metadata, session_id)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING id
            """,
            title,
            user_id,
            json.dumps(metadata or {}),
            session_id,
        )
        return row["id"]

    async def ensure_conversation(self, conversation_id: UUID) -> None:
        """Garante que a conversa exista; idempotente via ON CONFLICT DO NOTHING."""
        await self._pool.execute(
            """
            INSERT INTO conversations (id, metadata) VALUES ($1, '{}'::jsonb)
            ON CONFLICT (id) DO NOTHING
            """,
            conversation_id,
        )

    async def get_conversation_by_session_id(self, session_id: str) -> UUID | None:
        row = await self._pool.fetchrow(
            "SELECT id FROM conversations WHERE session_id = $1 LIMIT 1",
            session_id,
        )
        return row["id"] if row else None

    async def append_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        tool_calls: dict | None = None,
        tool_call_id: str | None = None,
        tokens: int | None = None,
    ) -> int:
        row = await self._pool.fetchrow(
            """
            INSERT INTO messages
                (conversation_id, role, content, tool_calls, tool_call_id, tokens)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            RETURNING id
            """,
            conversation_id,
            role,
            content,
            json.dumps(tool_calls) if tool_calls else None,
            tool_call_id,
            tokens,
        )
        return row["id"]

    async def get_messages(
        self, conversation_id: UUID, limit: int = 100
    ) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT id, role, content, tool_calls, tool_call_id, tokens, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC, id ASC
            LIMIT $2
            """,
            conversation_id,
            limit,
        )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Memories: write
    # -------------------------------------------------------------------------

    async def save(
        self,
        content: str,
        *,
        kind: MemoryKind = "fact",
        conversation_id: UUID | None = None,
        importance: int = 5,
        metadata: dict | None = None,
    ) -> UUID:
        import time
        t0 = time.monotonic()
        vec = await async_embed(content)
        row = await self._pool.fetchrow(
            """
            INSERT INTO memories
                (conversation_id, kind, content, embedding, importance, metadata)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id
            """,
            conversation_id,
            kind,
            content,
            vec,
            importance,
            json.dumps(metadata or {}),
        )
        mem_id: UUID = row["id"]
        log.info(
            "memory.save",
            memory_id=str(mem_id),
            kind=kind,
            importance=importance,
            content_len=len(content),
            conversation_id=str(conversation_id) if conversation_id else None,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )
        return mem_id

    # -------------------------------------------------------------------------
    # Memories: read
    # -------------------------------------------------------------------------

    async def search_vector(
        self,
        query: str,
        k: int = 5,
        kind: MemoryKind | None = None,
        min_importance: int = 1,
    ) -> list[MemoryEntry]:
        import time
        t0 = time.monotonic()
        qvec = await async_embed(query)

        if kind:
            rows = await self._pool.fetch(
                """
                SELECT id, conversation_id, kind, content, importance, metadata,
                       created_at, 1 - (embedding <=> $1) AS score
                FROM memories
                WHERE importance >= $2 AND kind = $3
                ORDER BY embedding <=> $1
                LIMIT $4
                """,
                qvec, min_importance, kind, k,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT id, conversation_id, kind, content, importance, metadata,
                       created_at, 1 - (embedding <=> $1) AS score
                FROM memories
                WHERE importance >= $2
                ORDER BY embedding <=> $1
                LIMIT $3
                """,
                qvec, min_importance, k,
            )

        entries = [_row_to_entry(r) for r in rows]
        await self._touch_access([e.id for e in entries if e.id])
        log.info(
            "memory.search",
            query=query[:60],
            method="vector",
            k=k,
            results_count=len(entries),
            top_score=round(entries[0].score or 0, 4) if entries else 0,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )
        return entries

    async def search_fts(
        self,
        query: str,
        k: int = 5,
        kind: MemoryKind | None = None,
    ) -> list[MemoryEntry]:
        if kind:
            rows = await self._pool.fetch(
                """
                SELECT id, conversation_id, kind, content, importance, metadata,
                       created_at,
                       ts_rank(tsv, plainto_tsquery('portuguese', unaccent($1))) AS score
                FROM memories
                WHERE tsv @@ plainto_tsquery('portuguese', unaccent($1))
                  AND kind = $2
                ORDER BY score DESC
                LIMIT $3
                """,
                query, kind, k,
            )
        else:
            rows = await self._pool.fetch(
                """
                SELECT id, conversation_id, kind, content, importance, metadata,
                       created_at,
                       ts_rank(tsv, plainto_tsquery('portuguese', unaccent($1))) AS score
                FROM memories
                WHERE tsv @@ plainto_tsquery('portuguese', unaccent($1))
                ORDER BY score DESC
                LIMIT $2
                """,
                query, k,
            )

        entries = [_row_to_entry(r) for r in rows]
        await self._touch_access([e.id for e in entries if e.id])
        return entries

    async def search_hybrid(
        self,
        query: str,
        k: int = 5,
        kind: MemoryKind | None = None,
        rrf_k: int = 60,
    ) -> SearchResult:
        """Reciprocal Rank Fusion: combina ranking vetorial e FTS."""
        import time
        t0 = time.monotonic()

        vec_results = await self.search_vector(query, k=k * 2, kind=kind)
        fts_results = await self.search_fts(query, k=k * 2, kind=kind)

        scores: dict[UUID, tuple[float, MemoryEntry]] = {}
        for rank, entry in enumerate(vec_results):
            if entry.id:
                scores[entry.id] = (1.0 / (rrf_k + rank + 1), entry)
        for rank, entry in enumerate(fts_results):
            if entry.id:
                prev_score, prev_entry = scores.get(entry.id, (0.0, entry))
                scores[entry.id] = (
                    prev_score + 1.0 / (rrf_k + rank + 1),
                    prev_entry,
                )

        merged = sorted(scores.values(), key=lambda t: t[0], reverse=True)[:k]
        entries = []
        for score, entry in merged:
            entry.score = score
            entries.append(entry)

        log.info(
            "memory.search",
            query=query[:60],
            method="hybrid",
            k=k,
            results_count=len(entries),
            top_score=round(entries[0].score or 0, 4) if entries else 0,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
        )
        return SearchResult(entries=entries, query=query, method="hybrid")

    # -------------------------------------------------------------------------
    # Skill Invocations
    # -------------------------------------------------------------------------

    async def save_skill_invocation(self, record: "SkillInvocationRecord") -> int:  # type: ignore[name-defined]  # noqa: F821
        from datetime import timezone
        from datetime import datetime as dt

        now = dt.now(tz=timezone.utc)
        row = await self._pool.fetchrow(
            """
            INSERT INTO skill_invocations
                (session_id, skill_name, skill_version, arguments, result,
                 success, error, latency_ms, started_at, finished_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            record.session_id,
            record.skill_name,
            record.skill_version,
            json.dumps(record.arguments),
            json.dumps(record.result) if record.result is not None else None,
            record.success,
            record.error,
            record.latency_ms,
            record.started_at or now,
            record.finished_at or now,
        )
        return row["id"]

    async def _touch_access(self, ids: list[UUID]) -> None:
        if not ids:
            return
        await self._pool.execute(
            """
            UPDATE memories
            SET last_accessed_at = NOW(), access_count = access_count + 1
            WHERE id = ANY($1::uuid[])
            """,
            ids,
        )


# ---------------------------------------------------------------------------
# Connection init & helpers
# ---------------------------------------------------------------------------

async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


def _row_to_entry(row: asyncpg.Record) -> MemoryEntry:
    raw_meta = row["metadata"]
    if isinstance(raw_meta, str):
        meta = json.loads(raw_meta)
    else:
        meta = raw_meta or {}

    return MemoryEntry(
        id=row["id"],
        conversation_id=row.get("conversation_id"),
        kind=row["kind"],
        content=row["content"],
        importance=row["importance"],
        metadata=meta,
        created_at=row.get("created_at"),
        score=float(row["score"]) if row.get("score") is not None else None,
    )
