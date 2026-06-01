"""Testes das memory tools — store mockado, sem Postgres ou API."""

from __future__ import annotations

import uuid

import pytest

from agent.memory.schemas import MemoryEntry, SearchResult
from agent.tools.builtin.memory_tools import LerMemoriaTool, SalvarMemoriaTool


def _fake_entry(content: str, score: float = 0.9) -> MemoryEntry:
    return MemoryEntry(
        id=uuid.uuid4(),
        kind="fact",
        content=content,
        importance=7,
        score=score,
    )


@pytest.fixture
def mock_store(mocker):
    store = mocker.AsyncMock()
    return store


async def test_salvar_memoria_returns_id(mock_store):
    mem_id = uuid.uuid4()
    mock_store.save.return_value = mem_id

    tool = SalvarMemoriaTool(store=mock_store)
    result = await tool.execute(content="O usuário usa Python", kind="fact", importance=7)

    assert result.ok is True
    assert result.output["memory_id"] == str(mem_id)
    assert result.output["saved"] is True
    mock_store.save.assert_called_once()


async def test_salvar_memoria_with_conversation_id(mock_store):
    conv_id = uuid.uuid4()
    mem_id = uuid.uuid4()
    mock_store.save.return_value = mem_id

    tool = SalvarMemoriaTool(store=mock_store, conversation_id=conv_id)
    result = await tool.execute(content="Contexto da conversa")

    assert result.ok is True
    call_kwargs = mock_store.save.call_args.kwargs
    assert call_kwargs["conversation_id"] == conv_id


async def test_salvar_memoria_error_handling(mock_store):
    mock_store.save.side_effect = RuntimeError("connection failed")

    tool = SalvarMemoriaTool(store=mock_store)
    result = await tool.execute(content="algum conteúdo")

    assert result.ok is False
    assert "connection failed" in result.error


async def test_ler_memoria_returns_relevant(mock_store):
    entries = [
        _fake_entry("O projeto se chama OpenClaw", score=0.95),
        _fake_entry("O usuário prefere Python", score=0.80),
    ]
    mock_store.search_hybrid.return_value = SearchResult(entries=entries, query="nome do projeto", method="hybrid")

    tool = LerMemoriaTool(store=mock_store)
    result = await tool.execute(query="nome do projeto", k=5)

    assert result.ok is True
    assert result.output["method"] == "hybrid"
    assert len(result.output["results"]) == 2
    assert result.output["results"][0]["content"] == "O projeto se chama OpenClaw"
    assert result.output["results"][0]["score"] == 0.95


async def test_ler_memoria_empty_results(mock_store):
    mock_store.search_hybrid.return_value = SearchResult(entries=[], query="xyz", method="hybrid")

    tool = LerMemoriaTool(store=mock_store)
    result = await tool.execute(query="xyz")

    assert result.ok is True
    assert result.output["results"] == []


async def test_ler_memoria_error_handling(mock_store):
    mock_store.search_hybrid.side_effect = RuntimeError("db error")

    tool = LerMemoriaTool(store=mock_store)
    result = await tool.execute(query="qualquer coisa")

    assert result.ok is False
    assert "db error" in result.error
