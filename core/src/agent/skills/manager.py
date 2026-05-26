"""
SkillManager: carrega, valida, busca e executa skills.
Reutiliza o embedder singleton da Fase 2 (agent.memory.embeddings).
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from agent.memory.embeddings import embed, embed_batch
from agent.observability.logger import get_logger
from agent.skills.cache import SkillEmbeddingCache as SkillRegistry
from agent.skills.loader import load_all_from_dir
from agent.skills.schema import (
    ApprovalCreated,
    SkillError,
    SkillInvocationRecord,
    SkillManifest,
    SkillMatch,
    SkillNotFound,
    SkillRequiresApproval,
    SkillResult,
)

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager
    from agent.memory.store import MemoryStore
    from agent.models.router import ModelRouter
    from agent.transports.base import BaseTransport

log = get_logger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SkillManager:
    def __init__(
        self,
        skills_dir: Path,
        transport: BaseTransport,
        memory_store: MemoryStore | None = None,
        cache_dir: Path | None = None,
        model_router: ModelRouter | None = None,
        approval_manager: ApprovalManager | None = None,
    ) -> None:
        self._skills_dir = skills_dir
        self._transport = transport
        self._memory_store = memory_store
        self._registry = SkillRegistry(cache_dir=cache_dir)
        self._model_router = model_router
        self._approval_manager = approval_manager

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load_all(self) -> int:
        """Carrega skills do disco, embeda descrições novas. Retorna quantidade."""
        self._registry.load_disk_cache()
        manifests = load_all_from_dir(self._skills_dir)

        to_embed = [m for m in manifests if self._registry.needs_reembed(m)]
        if to_embed:
            log.info("skill.embedding", count=len(to_embed))
            vectors = await embed_batch([m.description for m in to_embed])
            for manifest, vector in zip(to_embed, vectors):
                self._registry.add(manifest, vector)

        # Atualiza manifests que não precisaram de re-embed
        for m in manifests:
            if not self._registry.needs_reembed(m):
                self._registry.add(m, self._registry.embedding_for(m.name) or [])

        self._registry.save_disk_cache()
        log.info("skill.load_all.done", total=len(manifests))
        return len(manifests)

    async def reload(self, name: str | None = None) -> None:
        if name:
            self._registry.remove(name)
        else:
            self._registry.clear()
        await self.load_all()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list(self, tag: str | None = None) -> list[SkillManifest]:
        if tag:
            return self._registry.by_tag(tag)
        return self._registry.all()

    def get(self, name: str) -> SkillManifest:
        m = self._registry.get(name)
        if m is None:
            raise SkillNotFound(name)
        return m

    def has(self, name: str) -> bool:
        return self._registry.has(name)

    async def match(
        self, query: str, k: int = 3, must_have_tag: str | None = None
    ) -> list[SkillMatch]:
        """
        Busca semântica nas descrições + boost 0.2 por correspondência exata de nome.
        Retorna top-k ordenado por score descendente.
        """
        candidates = self._registry.all()
        if must_have_tag:
            candidates = [m for m in candidates if must_have_tag in m.tags]
        if not candidates:
            return []

        query_vec = await embed(query)
        all_embeddings = self._registry.all_embeddings()

        scores: list[SkillMatch] = []
        query_lower = query.lower()
        for manifest in candidates:
            vec = all_embeddings.get(manifest.name)
            if not vec:
                continue
            score = _cosine(query_vec, vec)
            # Boost por nome exato ou nome contido na query
            if manifest.name.lower() in query_lower or query_lower in manifest.name.lower():
                score = min(1.0, score + 0.2)
            scores.append(SkillMatch(manifest=manifest, score=score))

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:k]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(
        self,
        name: str,
        arguments: dict,
        session_id: UUID | None = None,
        channel: str = "cli",
        channel_ref: dict | None = None,
    ) -> SkillResult:
        manifest = self.get(name)

        # Without approval_manager, fall back to legacy behaviour (raises SkillRequiresApproval)
        if manifest.requires_approval and self._approval_manager is None:
            raise SkillRequiresApproval(name)

        from agent.skills.template_runner import TemplateSkillRunner as SkillRunner

        runner = SkillRunner(
            transport=self._transport,
            model_router=self._model_router,
            approval_manager=self._approval_manager,
        )

        started = time.monotonic()
        record = SkillInvocationRecord(
            session_id=session_id or UUID(int=0),
            skill_name=name,
            skill_version=manifest.version,
            arguments=arguments,
        )

        try:
            result = await runner.execute(
                manifest,
                arguments,
                session_id=str(session_id) if session_id else channel,
                channel=channel,
                channel_ref=channel_ref,
            )
        except Exception as exc:
            record.success = False
            record.error = str(exc)
            raise SkillError(f"Skill '{name}' falhou: {exc}") from exc
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            record.latency_ms = elapsed_ms
            if self._memory_store and session_id:
                await self._persist_invocation(record)

        # runner.execute() returns ApprovalRequest when requires_approval=True
        from agent.approvals.manager import ApprovalRequest

        if isinstance(result, ApprovalRequest):
            raise ApprovalCreated(result)

        record.success = True
        record.result = result.output
        return result

    async def _persist_invocation(self, record: SkillInvocationRecord) -> None:
        if not self._memory_store:
            return
        try:
            await self._memory_store.save_skill_invocation(record)
        except Exception as exc:
            log.warning("skill.persist.failed", error=str(exc))

    # ------------------------------------------------------------------
    # Anthropic tool schema (para injetar no LLM)
    # ------------------------------------------------------------------

    def to_tool_schema(self, manifest: SkillManifest) -> dict:
        """Converte manifest em tool schema compatível com a API Anthropic."""
        properties: dict = {}
        required: list[str] = []

        for arg in manifest.arguments:
            prop: dict = {"description": arg.description or arg.name}
            if arg.type == "enum":
                prop["type"] = "string"
                prop["enum"] = arg.values or []
            elif arg.type == "integer":
                prop["type"] = "integer"
            elif arg.type == "float":
                prop["type"] = "number"
            elif arg.type == "boolean":
                prop["type"] = "boolean"
            else:
                prop["type"] = "string"
            if arg.default is not None:
                prop["default"] = arg.default
            properties[arg.name] = prop
            if arg.required:
                required.append(arg.name)

        return {
            "name": f"skill__{manifest.name}",
            "description": manifest.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
