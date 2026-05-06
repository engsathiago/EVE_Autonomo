"""
Testes do OllamaTransport: mock HTTP via respx (não exige Ollama rodando).
"""
from __future__ import annotations

import json
import pytest
import respx
import httpx

from agent.models.base import Message, ModelNotPulledError, ToolSchema
from agent.models.transports.ollama import OllamaTransport

_BASE = "http://localhost:11434"


def _make_transport() -> OllamaTransport:
    return OllamaTransport(
        base_url=_BASE,
        http_client=httpx.AsyncClient(base_url=_BASE),
    )


def _ollama_chat_response(text: str = "pong", tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = [
            {"function": {"name": tc["name"], "arguments": tc["input"]}}
            for tc in tool_calls
        ]
    return {
        "model": "qwen2.5:7b",
        "message": msg,
        "done": True,
        "prompt_eval_count": 12,
        "eval_count": 6,
    }


# ---------------------------------------------------------------------------
# chat básico
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_chat_text_response() -> None:
    respx.post(f"{_BASE}/api/chat").mock(
        return_value=httpx.Response(200, json=_ollama_chat_response("pong"))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="ping")],
        model="qwen2.5:7b",
    )
    assert resp.text == "pong"
    assert resp.usage.input_tokens == 12
    assert resp.usage.output_tokens == 6


@pytest.mark.asyncio
@respx.mock
async def test_chat_with_tool_call() -> None:
    tool_calls = [{"name": "web_search", "input": {"query": "test"}}]
    respx.post(f"{_BASE}/api/chat").mock(
        return_value=httpx.Response(200, json=_ollama_chat_response("", tool_calls=tool_calls))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="search")],
        model="qwen2.5:7b",
        tools=[ToolSchema(name="web_search", description="Search", input_schema={"type": "object"})],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "web_search"


# ---------------------------------------------------------------------------
# Modelo não baixado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_model_not_pulled_raises() -> None:
    respx.post(f"{_BASE}/api/chat").mock(return_value=httpx.Response(404))
    transport = _make_transport()
    with pytest.raises(ModelNotPulledError, match="ollama pull"):
        await transport.chat(
            messages=[Message(role="user", content="hi")],
            model="nonexistent:7b",
        )


# ---------------------------------------------------------------------------
# Capabilities discovery — via /api/show
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_capabilities_from_api_show() -> None:
    respx.post(f"{_BASE}/api/show").mock(
        return_value=httpx.Response(200, json={
            "capabilities": ["completion", "tools"],
            "model_info": {"llama.context_length": 32768},
        })
    )
    transport = _make_transport()
    caps = await transport.get_model_capabilities("qwen2.5:7b")
    assert caps.tool_use is True
    assert caps.max_context == 32768


@pytest.mark.asyncio
@respx.mock
async def test_capabilities_fallback_to_family_table() -> None:
    """Quando /api/show não retorna 'capabilities', usa tabela por família."""
    respx.post(f"{_BASE}/api/show").mock(
        return_value=httpx.Response(200, json={"model_info": {}})
    )
    transport = _make_transport()
    caps = await transport.get_model_capabilities("hermes3:8b")
    assert caps.tool_use is True


@pytest.mark.asyncio
@respx.mock
async def test_capabilities_deepseek_r1_no_tool_use() -> None:
    respx.post(f"{_BASE}/api/show").mock(
        return_value=httpx.Response(200, json={"model_info": {}})
    )
    transport = _make_transport()
    caps = await transport.get_model_capabilities("deepseek-r1:14b")
    assert caps.tool_use is False


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_health_ok() -> None:
    respx.get(f"{_BASE}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "hermes3:8b"}]})
    )
    transport = _make_transport()
    status = await transport.health()
    assert status.ok
    assert status.models_loaded == 2


@pytest.mark.asyncio
@respx.mock
async def test_health_down() -> None:
    respx.get(f"{_BASE}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    transport = _make_transport()
    status = await transport.health()
    assert not status.ok
    assert "não responde" in status.message
