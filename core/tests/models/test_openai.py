"""
Testes do OpenAITransport: mock HTTP via respx.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from agent.models.base import Message, ToolSchema
from agent.models.transports.openai import OpenAITransport


def _make_transport() -> OpenAITransport:
    return OpenAITransport(
        api_key="test-key",
        http_client=httpx.AsyncClient(),
    )


def _openai_response(text: str = "pong", tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
            }
            for tc in tool_calls
        ]
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# ---------------------------------------------------------------------------
# chat básico
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_chat_text_response() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openai_response("pong"))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="ping")],
        model="gpt-4o-mini",
    )
    assert resp.text == "pong"
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5


@pytest.mark.asyncio
@respx.mock
async def test_chat_with_tool_call() -> None:
    tool_calls = [{"id": "call_abc", "name": "get_weather", "input": {"city": "São Paulo"}}]
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openai_response("", tool_calls=tool_calls))
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="weather?")],
        model="gpt-4o",
        tools=[ToolSchema(name="get_weather", description="Get weather", input_schema={"type": "object"})],
    )
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "get_weather"
    assert resp.tool_calls[0]["input"] == {"city": "São Paulo"}


@pytest.mark.asyncio
@respx.mock
async def test_usage_mapped_correctly() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openai_response())
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="hi")],
        model="gpt-4o-mini",
    )
    assert resp.usage.total == 15


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_health_ok() -> None:
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    transport = _make_transport()
    status = await transport.health()
    assert status.ok


@pytest.mark.asyncio
@respx.mock
async def test_health_no_key() -> None:
    transport = OpenAITransport(api_key="", http_client=httpx.AsyncClient())
    status = await transport.health()
    assert not status.ok
    assert "API_KEY" in status.message
