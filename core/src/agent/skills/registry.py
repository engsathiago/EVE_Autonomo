"""
SkillRegistry (Fase 9): CRUD + busca semântica para skills auto-geradas.

Persistência em PostgreSQL (tabela skills). Embedding como bytea + cosine em Python.
Sem pgvector direto — skills são poucas dezenas, Python é suficiente.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agent.observability.logger import get_logger
from agent.skills.embeddings import cosine, pack_embedding, unpack_embedding
from agent.skills.exceptions import SkillNotFound
from agent.skills.manifest import SkillManifestF9, manifest_to_dict

if TYPE_CHECKING:
    import asyncpg

log = get_logger(__name__)


class SkillRegistry:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def save(
        self,
        manifest: SkillManifestF9,
        embedding: list[float],
        *,
        status: str = "pending",
    ) -> None:
        embedding_bytes = pack_embedding(embedding)
        manifest_json = json.dumps(manifest_to_dict(manifest))
        try:
            await self._pool.execute(
                """
                INSERT INTO skills (
                    slug, version, status, manifest_json, embedding, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (slug) DO UPDATE SET
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    manifest_json = EXCLUDED.manifest_json,
                    embedding = EXCLUDED.embedding
                """,
                manifest.slug,
                manifest.version,
                status,
                manifest_json,
                embedding_bytes,
                manifest.created_at,
            )
        except Exception as exc:
            raise RuntimeError(f"Erro ao salvar skill '{manifest.slug}': {exc}") from exc

    async def get(self, slug: str) -> dict[str, Any]:
        row = await self._pool.fetchrow("SELECT * FROM skills WHERE slug = $1", slug)
        if row is None:
            raise SkillNotFound(slug)
        return dict(row)

    async def get_manifest(self, slug: str) -> SkillManifestF9:
        row = await self.get(slug)
        return SkillManifestF9(**json.loads(row["manifest_json"]))

    async def list(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = await self._pool.fetch(
                "SELECT * FROM skills WHERE status = $1 ORDER BY created_at DESC", status
            )
        else:
            rows = await self._pool.fetch("SELECT * FROM skills ORDER BY created_at DESC")
        return [dict(r) for r in rows]

    async def update_status(
        self,
        slug: str,
        status: str,
        *,
        critic_approval_id: str | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        params: list[Any] = [status, slug]
        extra_set = ""
        if status == "active":
            extra_set = ", promoted_at = $3"
            params = [status, slug, now]
        if critic_approval_id:
            params.append(critic_approval_id)
            extra_set += f", critic_approval_id = ${len(params)}"
        if rejection_reason:
            params.append(rejection_reason)
            extra_set += f", rejection_reason = ${len(params)}"

        await self._pool.execute(
            f"UPDATE skills SET status = $1{extra_set} WHERE slug = $2",
            *params,
        )

    async def record_execution(
        self,
        slug: str,
        *,
        success: bool,
        duration_seconds: float,
        sandbox_execution_id: str | None = None,
        mission_id: str | None = None,
        input_data: dict | None = None,
        output_data: dict | None = None,
        error_message: str | None = None,
    ) -> str:
        exec_id = uuid4().hex
        now = datetime.now(tz=UTC)

        await self._pool.execute(
            """
            INSERT INTO skill_executions (
                id, skill_slug, sandbox_execution_id, mission_id,
                input_json, output_json, success, duration_seconds,
                error_message, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            exec_id,
            slug,
            sandbox_execution_id,
            mission_id,
            json.dumps(input_data or {}),
            json.dumps(output_data) if output_data is not None else None,
            success,
            duration_seconds,
            error_message,
            now,
        )

        # Atualiza stats da skill
        if success:
            await self._pool.execute(
                """
                UPDATE skills SET
                    executions_count = executions_count + 1,
                    successes_count = successes_count + 1,
                    last_used_at = $2,
                    avg_duration_seconds = CASE
                        WHEN avg_duration_seconds IS NULL THEN $3
                        ELSE (avg_duration_seconds * executions_count + $3) / (executions_count + 1)
                    END
                WHERE slug = $1
                """,
                slug,
                now,
                duration_seconds,
            )
        else:
            await self._pool.execute(
                """
                UPDATE skills SET
                    executions_count = executions_count + 1,
                    failures_count = failures_count + 1,
                    last_used_at = $2
                WHERE slug = $1
                """,
                slug,
                now,
            )

        return exec_id

    async def save_candidate(
        self,
        proposed_slug: str,
        source_execution_ids: list[str],
        pattern_cluster_score: float,
        status: str = "synthesizing",
        llm_prompt: str | None = None,
        llm_response: str | None = None,
        validation_report: dict | None = None,
    ) -> str:
        candidate_id = uuid4().hex
        await self._pool.execute(
            """
            INSERT INTO skill_candidates (
                id, proposed_slug, source_execution_ids, pattern_cluster_score,
                llm_synthesis_prompt, llm_synthesis_response,
                validation_report_json, status, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            candidate_id,
            proposed_slug,
            json.dumps(source_execution_ids),
            pattern_cluster_score,
            llm_prompt,
            llm_response,
            json.dumps(validation_report) if validation_report else None,
            status,
            datetime.now(tz=UTC),
        )
        return candidate_id

    async def update_candidate(
        self,
        candidate_id: str,
        *,
        status: str,
        validation_report: dict | None = None,
        llm_response: str | None = None,
    ) -> None:
        now = datetime.now(tz=UTC)
        await self._pool.execute(
            """
            UPDATE skill_candidates SET
                status = $2,
                resolved_at = CASE WHEN $2 IN ('approved','rejected') THEN $3 ELSE resolved_at END,
                validation_report_json = COALESCE($4, validation_report_json),
                llm_synthesis_response = COALESCE($5, llm_synthesis_response)
            WHERE id = $1
            """,
            candidate_id,
            status,
            now,
            json.dumps(validation_report) if validation_report else None,
            llm_response,
        )

    # ── Busca semântica ───────────────────────────────────────────────────────

    async def search(
        self,
        intent_embedding: list[float],
        top_k: int = 3,
        min_score: float = 0.78,
        status_filter: str = "active",
    ) -> list[tuple[str, float]]:
        """
        Retorna lista de (slug, score) ordenada por cosine descendente.
        Só retorna skills com status=status_filter e score >= min_score.
        """
        rows = await self._pool.fetch(
            "SELECT slug, embedding FROM skills WHERE status = $1 AND embedding IS NOT NULL",
            status_filter,
        )
        results: list[tuple[str, float]] = []
        for row in rows:
            if row["embedding"] is None:
                continue
            vec = unpack_embedding(bytes(row["embedding"]))
            score = cosine(intent_embedding, vec)
            if score >= min_score:
                results.append((row["slug"], score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def stats(self) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT slug, status, executions_count, successes_count, failures_count,
                   last_used_at, avg_duration_seconds
            FROM skills ORDER BY executions_count DESC
            """
        )
        result = []
        for row in rows:
            r = dict(row)
            total = r["executions_count"] or 0
            succs = r["successes_count"] or 0
            r["success_rate"] = round(succs / total, 3) if total > 0 else None
            result.append(r)
        return result

    async def recent_executions(self, slug: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT success, duration_seconds, created_at, error_message
            FROM skill_executions WHERE skill_slug = $1
            ORDER BY created_at DESC LIMIT $2
            """,
            slug,
            limit,
        )
        return [dict(r) for r in rows]
