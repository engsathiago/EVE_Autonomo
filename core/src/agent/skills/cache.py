"""
Cache in-memory de skills da Fase 3 (template .md) com vetores de embedding.
Hash do manifest detecta mudanças e dispara re-embedding seletivo.

Fase 9 usa SkillRegistry (registry.py) para skills auto-geradas (.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.observability.logger import get_logger
from agent.skills.schema import SkillManifest

log = get_logger(__name__)

_CACHE_VERSION = 1


class SkillEmbeddingCache:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self._manifests: dict[str, SkillManifest] = {}
        self._embeddings: dict[str, list[float]] = {}
        self._cache_dir = cache_dir

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, manifest: SkillManifest, embedding: list[float]) -> None:
        self._manifests[manifest.name] = manifest
        self._embeddings[manifest.name] = embedding

    def remove(self, name: str) -> None:
        self._manifests.pop(name, None)
        self._embeddings.pop(name, None)

    def clear(self) -> None:
        self._manifests.clear()
        self._embeddings.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def has(self, name: str) -> bool:
        return name in self._manifests

    def get(self, name: str) -> SkillManifest | None:
        return self._manifests.get(name)

    def all(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def by_tag(self, tag: str) -> list[SkillManifest]:
        return [m for m in self._manifests.values() if tag in m.tags]

    def embedding_for(self, name: str) -> list[float] | None:
        return self._embeddings.get(name)

    def all_embeddings(self) -> dict[str, list[float]]:
        return dict(self._embeddings)

    def needs_reembed(self, manifest: SkillManifest) -> bool:
        """True se a skill não está no cache ou o hash mudou."""
        existing = self._manifests.get(manifest.name)
        if existing is None:
            return True
        return existing.content_hash != manifest.content_hash

    # ------------------------------------------------------------------
    # Disk cache (opcional) — evita re-embedar ao reiniciar o processo
    # ------------------------------------------------------------------

    def _cache_path(self) -> Path | None:
        if not self._cache_dir:
            return None
        return self._cache_dir / f"skill_embeddings_v{_CACHE_VERSION}.json"

    def load_disk_cache(self) -> None:
        path = self._cache_path()
        if not path or not path.exists():
            return
        try:
            data: dict[str, Any] = json.loads(path.read_text())
            for name, entry in data.items():
                self._embeddings[name] = entry["vector"]
                # Registra apenas o hash; manifest completo vem do load_all
                if name not in self._manifests:
                    # Placeholder até o manifest ser carregado do disco
                    self._manifests[name] = SkillManifest(
                        name=name,
                        description="",
                        content_hash=entry["hash"],
                    )
            log.debug("skill.cache.loaded", count=len(data))
        except Exception as exc:
            log.warning("skill.cache.load_failed", error=str(exc))

    def save_disk_cache(self) -> None:
        path = self._cache_path()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                name: {
                    "hash": self._manifests[name].content_hash,
                    "vector": self._embeddings[name],
                }
                for name in self._embeddings
                if name in self._manifests
            }
            path.write_text(json.dumps(data))
            log.debug("skill.cache.saved", count=len(data))
        except Exception as exc:
            log.warning("skill.cache.save_failed", error=str(exc))
