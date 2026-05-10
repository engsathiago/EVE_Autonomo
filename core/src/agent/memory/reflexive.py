"""
Memória reflexiva: lições aprendidas pelo agente a partir de missões concluídas.

Diferença da memória semântica (já existente):
- Semântica: fatos sobre o mundo ("Thiago mora em SP")
- Reflexiva: padrões observados pelo agente ("missões de conteúdo precisam de 7d de buffer")

Usa o mesmo EmbeddingProvider (embed()) já carregado pela memória semântica.
Não cria provider novo.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
from pydantic import BaseModel

from agent.memory.embeddings import embed
from agent.observability.logger import get_logger

log = get_logger(__name__)

_DECAY_RATE_PER_DAY = 0.1
_FORGOTTEN_THRESHOLD = 0.1
_FORGOTTEN_GRACE_DAYS = 60


class ReflexiveInsight(BaseModel):
    id: UUID
    insight: str
    source_mission_id: UUID | None
    relevance_score: float
    times_recalled: int
    last_recalled_at: datetime | None
    created_at: datetime


class ReflexiveMemory:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(
        self,
        insight: str,
        *,
        source_mission: UUID | None = None,
    ) -> UUID:
        insight_id = uuid4()
        embedding = await embed(insight)

        await self._pool.execute(
            """
            INSERT INTO reflexive_memory
                (id, insight, source_mission_id, embedding, relevance_score)
            VALUES ($1, $2, $3, $4, $5)
            """,
            insight_id,
            insight,
            source_mission,
            embedding,
            0.5,
        )
        log.info("reflexive_memory.added", insight_id=str(insight_id))
        return insight_id

    async def recall(self, query: str, *, top_k: int = 3) -> list[ReflexiveInsight]:
        """
        Busca top-k insights por similaridade coseno.
        Incrementa times_recalled para cada resultado retornado.
        """
        query_vec = await embed(query)

        rows = await self._pool.fetch(
            """
            SELECT *, (embedding <=> $1) AS distance
            FROM reflexive_memory
            WHERE forgotten = FALSE
            ORDER BY distance
            LIMIT $2
            """,
            query_vec,
            top_k,
        )

        if not rows:
            return []

        ids = [r["id"] for r in rows]
        now = datetime.now(tz=UTC)

        # Atualiza times_recalled e last_recalled_at em lote
        await self._pool.execute(
            """
            UPDATE reflexive_memory
               SET times_recalled = times_recalled + 1, last_recalled_at = $2
             WHERE id = ANY($1::uuid[])
            """,
            ids,
            now,
        )

        return [_row_to_insight(r) for r in rows]

    async def decay(self) -> int:
        """
        Decai relevance_score de insights não lembrados em 60d: -0.1/dia.
        Insights abaixo de 0.1 são marcados como forgotten (nunca deletados).
        Retorna quantidade de insights afetados.
        """
        now = datetime.now(tz=UTC)
        result = await self._pool.execute(
            f"""
            UPDATE reflexive_memory
               SET relevance_score = GREATEST(0, relevance_score - {_DECAY_RATE_PER_DAY}),
                   forgotten = CASE
                       WHEN relevance_score - {_DECAY_RATE_PER_DAY} < {_FORGOTTEN_THRESHOLD}
                           THEN TRUE
                       ELSE forgotten
                   END
             WHERE forgotten = FALSE
               AND (last_recalled_at IS NULL OR
                    last_recalled_at < $1 - INTERVAL '{_FORGOTTEN_GRACE_DAYS} days')
            """,
            now,
        )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            log.info("reflexive_memory.decayed", count=count)
        return count

    async def list_all(
        self, *, include_forgotten: bool = False, limit: int = 50
    ) -> list[ReflexiveInsight]:
        if include_forgotten:
            rows = await self._pool.fetch(
                "SELECT * FROM reflexive_memory ORDER BY created_at DESC LIMIT $1", limit
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM reflexive_memory"
                " WHERE forgotten = FALSE"
                " ORDER BY relevance_score DESC LIMIT $1",
                limit,
            )
        return [_row_to_insight(r) for r in rows]

    async def mark_forgotten(self, insight_id: UUID) -> None:
        await self._pool.execute(
            "UPDATE reflexive_memory SET forgotten = TRUE WHERE id = $1",
            insight_id,
        )
        log.info("reflexive_memory.forgotten", insight_id=str(insight_id))


def _row_to_insight(row: asyncpg.Record) -> ReflexiveInsight:
    return ReflexiveInsight(
        id=row["id"],
        insight=row["insight"],
        source_mission_id=row["source_mission_id"],
        relevance_score=row["relevance_score"],
        times_recalled=row["times_recalled"],
        last_recalled_at=row["last_recalled_at"],
        created_at=row["created_at"],
    )
