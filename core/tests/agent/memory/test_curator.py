"""Testes do Curator — sem chamadas reais à API Anthropic."""

from __future__ import annotations

import json

import pytest

from agent.memory.curator import Curator
from agent.memory.schemas import CuratorDecision


def _mock_response(data: dict):
    """Cria um mock do response da API Anthropic."""

    class FakeContent:
        text = json.dumps(data)

    class FakeResp:
        content = [FakeContent()]

    return FakeResp()


@pytest.fixture
def mock_client(mocker):
    client = mocker.AsyncMock()
    return client


async def test_smalltalk_not_persisted(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        {"persist": False, "reason": "smalltalk", "importance": 1, "kind": "note", "extracted_content": None}
    )
    curator = Curator(client=mock_client)
    decision = await curator.should_persist("oi tudo bem?", "Tudo bem! E com você?")

    assert decision.persist is False
    assert decision.importance == 1


async def test_user_fact_persisted(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        {
            "persist": True,
            "reason": "fato sobre localização e profissão do usuário",
            "importance": 7,
            "kind": "fact",
            "extracted_content": "Usuário é desenvolvedor em São Paulo",
        }
    )
    curator = Curator(client=mock_client)
    decision = await curator.should_persist(
        "sou dev em São Paulo",
        "Entendido! Posso levar isso em conta nas recomendações.",
    )

    assert decision.persist is True
    assert decision.kind == "fact"
    assert decision.importance >= 5
    assert decision.extracted_content is not None


async def test_curator_failure_safe(mock_client):
    """Erro no client → retorna persist=False sem propagar exceção."""
    mock_client.messages.create.side_effect = RuntimeError("timeout")
    curator = Curator(client=mock_client)
    decision = await curator.should_persist("mensagem qualquer", "resposta qualquer")

    assert decision.persist is False
    assert "curator_error" in decision.reason


async def test_malformed_json_fallback(mock_client):
    """JSON malformado na resposta → fallback seguro."""

    class FakeContent:
        text = "isso não é json { broken"

    class FakeResp:
        content = [FakeContent()]

    mock_client.messages.create.return_value = FakeResp()
    curator = Curator(client=mock_client)
    decision = await curator.should_persist("teste", "resposta")

    assert isinstance(decision, CuratorDecision)
    assert decision.persist is False
