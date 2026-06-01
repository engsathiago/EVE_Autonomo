"""
Testa o parser de linguagem natural → cron expression.
20 frases PT-BR cobrindo os casos mais comuns.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.scheduler.parser import (
    CronParseError,
    _extract_cron,
    _validate_cron,
    next_runs,
    parse_natural,
)

# ---------------------------------------------------------------------------
# Testes de _extract_cron (sem LLM)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0 9 * * 1", "0 9 * * 1"),
    ("*/30 * * * *", "*/30 * * * *"),
    ("0 0 1 * *", "0 0 1 * *"),
    ("0 8 * * *", "0 8 * * *"),
    ("  0 18 * * 1-5  ", "0 18 * * 1-5"),
    ("Cron: 0 9 * * 1\n", "0 9 * * 1"),
    ("The answer is */2 * * * *", "*/2 * * * *"),
])
def test_extract_cron_valid(raw: str, expected: str) -> None:
    assert _extract_cron(raw) == expected


def test_extract_cron_invalid() -> None:
    with pytest.raises(CronParseError):
        _extract_cron("não é uma cron expression válida")


# ---------------------------------------------------------------------------
# Testes de _validate_cron (sem LLM)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr", [
    "0 9 * * 1",
    "*/30 * * * *",
    "0 0 1 * *",
    "0 8 * * *",
    "0 18 * * 1-5",
    "*/2 * * * *",
    "0 0 * * *",
    "30 6 * * 1-5",
])
def test_validate_cron_valid(expr: str) -> None:
    _validate_cron(expr, original=expr)  # não deve lançar exceção


@pytest.mark.parametrize("expr", [
    "99 25 * * *",   # hora inválida
    "abc def ghi",   # não é cron
    "60 * * * *",    # minuto inválido
])
def test_validate_cron_invalid(expr: str) -> None:
    with pytest.raises(CronParseError):
        _validate_cron(expr, original=expr)


# ---------------------------------------------------------------------------
# Testes de next_runs
# ---------------------------------------------------------------------------

def test_next_runs_returns_n_items() -> None:
    runs = next_runs("0 9 * * 1", n=3)
    assert len(runs) == 3


def test_next_runs_ordered() -> None:
    runs = next_runs("*/5 * * * *", n=5)
    for i in range(len(runs) - 1):
        assert runs[i] < runs[i + 1]


# ---------------------------------------------------------------------------
# Testes de parse_natural (com LLM mockado)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("phrase,expected_cron", [
    ("toda segunda às 9h", "0 9 * * 1"),
    ("todo dia às 8h", "0 8 * * *"),
    ("a cada 30 minutos", "*/30 * * * *"),
    ("a cada 2 minutos", "*/2 * * * *"),
    ("todo dia 1 do mês", "0 0 1 * *"),
    ("dias úteis às 18h", "0 18 * * 1-5"),
    ("every day at 8am", "0 8 * * *"),
    ("every monday at 9am", "0 9 * * 1"),
    ("every 30 minutes", "*/30 * * * *"),
    ("weekdays at 6pm", "0 18 * * 1-5"),
])
async def test_parse_natural_phrases(phrase: str, expected_cron: str) -> None:
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.text = expected_cron
    mock_llm.chat = AsyncMock(return_value=mock_response)

    result = await parse_natural(phrase, mock_llm)
    assert result == expected_cron


@pytest.mark.asyncio
async def test_parse_natural_llm_returns_extra_text() -> None:
    """LLM retorna texto extra além da cron expression."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "The cron expression is: 0 9 * * 1"
    mock_llm.chat = AsyncMock(return_value=mock_response)

    result = await parse_natural("toda segunda às 9h", mock_llm)
    assert result == "0 9 * * 1"


@pytest.mark.asyncio
async def test_parse_natural_llm_returns_invalid_raises() -> None:
    """LLM retorna expressão inválida → CronParseError."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "not a cron expression at all"
    mock_llm.chat = AsyncMock(return_value=mock_response)

    with pytest.raises(CronParseError):
        await parse_natural("hora nenhuma", mock_llm)


@pytest.mark.asyncio
async def test_parse_natural_llm_unavailable_raises() -> None:
    """LLM indisponível → CronParseError."""
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(side_effect=RuntimeError("connection error"))

    with pytest.raises(CronParseError):
        await parse_natural("toda segunda", mock_llm)
