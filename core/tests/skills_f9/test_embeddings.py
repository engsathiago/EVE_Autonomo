"""Testes do módulo de embeddings F9."""
from __future__ import annotations

import struct

import pytest

from agent.skills.embeddings import cosine, pack_embedding, unpack_embedding


def test_pack_unpack_roundtrip() -> None:
    vec = [0.1, 0.2, 0.3, 0.4]
    packed = pack_embedding(vec)
    unpacked = unpack_embedding(packed)
    assert len(unpacked) == len(vec)
    for a, b in zip(unpacked, vec):
        assert abs(a - b) < 1e-6


def test_pack_returns_bytes() -> None:
    vec = [1.0, 0.0, 0.0]
    result = pack_embedding(vec)
    assert isinstance(result, bytes)
    assert len(result) == 3 * 4  # 3 floats * 4 bytes each


def test_cosine_identical() -> None:
    vec = [1.0, 0.0, 0.0]
    assert abs(cosine(vec, vec) - 1.0) < 1e-6


def test_cosine_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine(a, b)) < 1e-6


def test_cosine_zero_vector() -> None:
    a = [0.0, 0.0]
    b = [1.0, 0.0]
    assert cosine(a, b) == 0.0


def test_cosine_opposite() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(cosine(a, b) + 1.0) < 1e-6


def test_cosine_threshold() -> None:
    # Dois vetores próximos devem ter cosine > 0.78
    a = [1.0, 0.1, 0.0]
    b = [0.9, 0.2, 0.0]
    score = cosine(a, b)
    assert score > 0.78
