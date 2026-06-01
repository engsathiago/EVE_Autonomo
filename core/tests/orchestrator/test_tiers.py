"""Testa TierClassifier — classificação mockada e roteamento por tier."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.orchestrator.tiers import _DEFAULT_ON_PARSE_ERROR, ExecutionTier, TierClassifier


def _make_router(response_text: str) -> MagicMock:
    router = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = response_text
    router.chat = AsyncMock(return_value=mock_resp)
    return router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "llm_response,expected",
    [
        ("INSTANT", ExecutionTier.INSTANT),
        ("FAST", ExecutionTier.FAST),
        ("STRATEGIC", ExecutionTier.STRATEGIC),
        ("EPIC", ExecutionTier.EPIC),
        ("instant", ExecutionTier.INSTANT),  # case-insensitive
        ("  FAST  ", ExecutionTier.FAST),  # whitespace
    ],
)
async def test_classify_valid_responses(llm_response: str, expected: ExecutionTier) -> None:
    classifier = TierClassifier(_make_router(llm_response), cache_ttl_s=0)
    result = await classifier.classify("qualquer tarefa")
    assert result == expected


@pytest.mark.asyncio
async def test_classify_invalid_response_falls_back() -> None:
    """Resposta fora do enum → fallback STRATEGIC."""
    classifier = TierClassifier(_make_router("DESCONHECIDO"), cache_ttl_s=0)
    result = await classifier.classify("tarefa qualquer")
    assert result == _DEFAULT_ON_PARSE_ERROR


@pytest.mark.asyncio
async def test_classify_llm_error_falls_back() -> None:
    """LLM indisponível → fallback STRATEGIC."""
    router = MagicMock()
    router.chat = AsyncMock(side_effect=RuntimeError("timeout"))
    classifier = TierClassifier(router, cache_ttl_s=0)
    result = await classifier.classify("tarefa qualquer")
    assert result == _DEFAULT_ON_PARSE_ERROR


@pytest.mark.asyncio
async def test_classify_cache_hit() -> None:
    """Segunda chamada com mesmo conteúdo usa cache (LLM não é chamado de novo)."""
    router = _make_router("FAST")
    classifier = TierClassifier(router, cache_ttl_s=300)

    r1 = await classifier.classify("mesma tarefa")
    r2 = await classifier.classify("mesma tarefa")

    assert r1 == r2 == ExecutionTier.FAST
    # LLM só foi chamado 1x (segunda chamada usou cache)
    assert router.chat.call_count == 1


@pytest.mark.asyncio
async def test_classify_cache_miss_different_content() -> None:
    """Conteúdos diferentes → duas chamadas ao LLM."""
    router = _make_router("INSTANT")
    classifier = TierClassifier(router, cache_ttl_s=300)

    await classifier.classify("tarefa A")
    await classifier.classify("tarefa B")

    assert router.chat.call_count == 2
