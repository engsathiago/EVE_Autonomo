"""
Testes do AnthropicTransport (models/transports): mock HTTP via respx.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from agent.models.base import Message, ToolSchema
from agent.models.transports.anthropic import AnthropicTransport


def _make_transport() -> AnthropicTransport:
    return AnthropicTransport(
        api_key="test-key",
        http_client=httpx.AsyncClient(),
    )


def _anthropic_response(text: str = "pong", tool_calls: list | None = None) -> dict:
    content = [{"type": "text", "text": text}]
    if tool_calls:
        for tc in tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"],
            })
    return {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": "claude-haiku-4-5",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


# ---------------------------------------------------------------------------
# chat básico
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_chat_text_response() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_anthropic_response("pong"))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="ping")],
        model="claude-haiku-4-5",
    )
    assert resp.text == "pong"
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5
    assert resp.tool_calls == []


@pytest.mark.asyncio
@respx.mock
async def test_chat_with_tool_call() -> None:
    tool_calls = [{"id": "tc1", "name": "web_search", "input": {"query": "test"}}]
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_anthropic_response("", tool_calls=tool_calls))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="search something")],
        model="claude-haiku-4-5",
        tools=[ToolSchema(name="web_search", description="Search", input_schema={"type": "object", "properties": {"query": {"type": "string"}}})],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "web_search"
    assert resp.tool_calls[0]["input"] == {"query": "test"}


# ---------------------------------------------------------------------------
# system message separado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_system_message_extracted() -> None:
    """Mensagem com role=system deve virar parâmetro 'system' na API Anthropic."""
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_anthropic_response())
    )
    transport = _make_transport()
    await transport.chat(
        messages=[
            Message(role="system", content="You are helpful."),
            Message(role="user", content="hello"),
        ],
        model="claude-haiku-4-5",
    )
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "You are helpful."
    assert all(m["role"] != "system" for m in body["messages"])


# ---------------------------------------------------------------------------
# uso e custo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_usage_is_mapped() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_anthropic_response())
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="hi")],
        model="claude-haiku-4-5",
    )
    assert resp.usage.total == 15


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_health_ok() -> None:
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    transport = _make_transport()
    status = await transport.health()
    assert status.ok


@pytest.mark.asyncio
@respx.mock
async def test_health_bad_key() -> None:
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"type": "authentication_error"}})
    )
    transport = _make_transport()
    status = await transport.health()
    assert not status.ok
    assert "inválida" in status.message or "key" in status.message.lower()
