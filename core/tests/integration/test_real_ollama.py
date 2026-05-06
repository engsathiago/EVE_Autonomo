"""
Testes de integração com Ollama real. Pula automaticamente se Ollama não responder.
Execute com: pytest -m integration
"""
from __future__ import annotations

import os
import pytest

from agent.models.base import Message
from agent.models.transports.ollama import OllamaTransport


def _get_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_ollama_health() -> None:
    transport = OllamaTransport(base_url=_get_base_url())
    status = await transport.health()
    if not status.ok:
        pytest.skip(f"Ollama não disponível: {status.message}")
    assert status.ok


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_ollama_chat() -> None:
    transport = OllamaTransport(base_url=_get_base_url())
    health = await transport.health()
    if not health.ok:
        pytest.skip("Ollama não disponível")

    models = await transport.list_models()
    if not models:
        pytest.skip("Nenhum modelo Ollama disponível")

    model_id = models[0].model_id
    resp = await transport.chat(
        messages=[Message(role="user", content="Responda apenas com a palavra 'pong'.")],
        model=model_id,
        max_tokens=32,
    )
    assert "pong" in resp.text.lower()
    assert resp.usage.output_tokens > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_ollama_capabilities_discovery() -> None:
    transport = OllamaTransport(base_url=_get_base_url())
    health = await transport.health()
    if not health.ok:
        pytest.skip("Ollama não disponível")

    models = await transport.list_models()
    if not models:
        pytest.skip("Nenhum modelo Ollama disponível")

    # Capabilities deve ser possível para qualquer modelo disponível
    model_id = models[0].model_id
    caps = await transport.get_model_capabilities(model_id)
    assert caps is not None
    assert caps.max_context > 0
