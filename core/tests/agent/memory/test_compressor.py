"""Testes do ContextCompressor — sem chamadas reais à API Anthropic."""
from __future__ import annotations

import pytest

from agent.memory.compressor import ContextCompressor


def _make_messages(n: int) -> list[dict]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"mensagem {i} " * 20})
    return msgs


@pytest.fixture
def mock_client(mocker):
    client = mocker.AsyncMock()
    return client


async def test_no_compression_below_threshold(mock_client):
    """Histórico curto retorna inalterado sem chamar a API."""
    compressor = ContextCompressor(client=mock_client, token_threshold=10_000, keep_recent=4)
    msgs = _make_messages(4)

    result, summary = await compressor.maybe_compress(msgs)

    assert result == msgs
    assert summary is None
    mock_client.messages.create.assert_not_called()


async def test_compression_preserves_recent(mock_client):
    """Histórico longo: as últimas keep_recent mensagens ficam intactas."""

    class FakeContent:
        text = "## Identidade\nUsuário é dev.\n## Decisões\nUsar Python."

    class FakeResp:
        content = [FakeContent()]

    mock_client.messages.create.return_value = FakeResp()

    keep = 4
    compressor = ContextCompressor(client=mock_client, token_threshold=100, keep_recent=keep)
    msgs = _make_messages(20)

    result, summary = await compressor.maybe_compress(msgs)

    assert summary is not None
    recent_in_result = [m for m in result if m.get("role") in ("user", "assistant")]
    assert recent_in_result == msgs[-keep:]


async def test_summary_added_as_system(mock_client):
    """Resumo é injetado como bloco role=system."""

    class FakeContent:
        text = "resumo da conversa"

    class FakeResp:
        content = [FakeContent()]

    mock_client.messages.create.return_value = FakeResp()

    compressor = ContextCompressor(client=mock_client, token_threshold=50, keep_recent=2)
    msgs = _make_messages(16)

    result, summary = await compressor.maybe_compress(msgs)

    summary_blocks = [m for m in result if m.get("role") == "system"]
    assert any("<resumo_da_conversa>" in m["content"] for m in summary_blocks)
    assert summary == "resumo da conversa"


async def test_system_messages_preserved(mock_client):
    """Mensagens role=system existentes são mantidas antes do resumo."""

    class FakeContent:
        text = "resumo"

    class FakeResp:
        content = [FakeContent()]

    mock_client.messages.create.return_value = FakeResp()

    compressor = ContextCompressor(client=mock_client, token_threshold=50, keep_recent=2)
    msgs = [{"role": "system", "content": "instrução do sistema"}] + _make_messages(14)

    result, summary = await compressor.maybe_compress(msgs)

    assert result[0]["role"] == "system"
    assert result[0]["content"] == "instrução do sistema"
