"""
Testes do OpenRouterTransport: headers obrigatórios e herança de OpenAITransport.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from agent.models.base import Message
from agent.models.transports.openrouter import OpenRouterTransport


def _make_transport(referer: str = "https://test.example", title: str = "test") -> OpenRouterTransport:
    return OpenRouterTransport(
        api_key="or-test-key",
        http_referer=referer,
        x_title=title,
        http_client=httpx.AsyncClient(),
    )


def _openrouter_response(text: str = "pong") -> dict:
    return {
        "id": "gen-123",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
    }


# ---------------------------------------------------------------------------
# Headers obrigatórios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_required_headers_present() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openrouter_response())
    )
    transport = _make_transport(referer="https://myapp.com", title="MyApp")
    await transport.chat(
        messages=[Message(role="user", content="ping")],
        model="deepseek/deepseek-chat",
    )
    headers = route.calls[0].request.headers
    assert headers.get("http-referer") == "https://myapp.com"
    assert headers.get("x-title") == "MyApp"


@pytest.mark.asyncio
@respx.mock
async def test_base_url_is_openrouter() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_openrouter_response())
    )
    transport = _make_transport()
    resp = await transport.chat(
        messages=[Message(role="user", content="hi")],
        model="anthropic/claude-3.5-sonnet",
    )
    assert resp.text == "pong"
    assert route.called


# ---------------------------------------------------------------------------
# Nome do provider
# ---------------------------------------------------------------------------


def test_provider_name() -> None:
    transport = _make_transport()
    assert transport.name == "openrouter"


# ---------------------------------------------------------------------------
# Sem API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_no_key() -> None:
    transport = OpenRouterTransport(api_key="", http_client=httpx.AsyncClient())
    status = await transport.health()
    assert not status.ok
    assert "API_KEY" in status.message
