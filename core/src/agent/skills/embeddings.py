"""
SkillEmbedder (Fase 9): indexa skills no banco via embeddings.

Reutiliza o embedder singleton da memória (F2/F5/F7).
Serialização: numpy float32 → bytes (struct pack) armazenado em bytea no Postgres.
Cosine similarity calculado em Python — skills são poucas dezenas, não precisa de pgvector.
"""

from __future__ import annotations

import math
import struct


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity entre dois vetores (lista de float)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def pack_embedding(vec: list[float]) -> bytes:
    """Serializa vetor como bytes float32 (little-endian)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_embedding(data: bytes) -> list[float]:
    """Desserializa bytes float32 → lista de float."""
    n = len(data) // 4
    return list(struct.unpack(f"<{n}f", data))


async def embed_text(text: str) -> list[float]:
    """Embeda texto usando o modelo singleton da memória."""
    from agent.memory.embeddings import embed

    return await embed(text)


async def embed_skill_text(embedding_text: str) -> list[float]:
    """Embeda o embedding_text do manifesto para busca semântica."""
    return await embed_text(embedding_text)
