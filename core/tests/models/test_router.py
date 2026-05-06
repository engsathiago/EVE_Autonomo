"""
Testes do ModelRouter: parsing, resolução, fallback chain, capability check.
"""
from __future__ import annotations

import asyncio
import pytest

from agent.models.base import (
    Capabilities,
    CapabilityMismatchError,
    ChatResponse,
    HealthStatus,
    Message,
    ModelInfo,
    Usage,
)
from agent.models.registry import TransportRegistry
from agent.models.router import ModelRouter, _build_effective_chain, parse_model_string


# ---------------------------------------------------------------------------
# parse_model_string
# ---------------------------------------------------------------------------

def test_parse_anthropic() -> None:
    provider, model = parse_model_string("anthropic:claude-haiku-4-5")
    assert provider == "anthropic"
    assert model == "claude-haiku-4-5"


def test_parse_ollama_with_tag() -> None:
    provider, model = parse_model_string("ollama:qwen2.5:32b")
    assert provider == "ollama"
    assert model == "qwen2.5:32b"


def test_parse_openrouter_slash() -> None:
    provider, model = parse_model_string("openrouter:deepseek/deepseek-chat")
    assert provider == "openrouter"
    assert model == "deepseek/deepseek-chat"


def test_parse_invalid_no_colon() -> None:
    with pytest.raises(ValueError, match="inválida"):
        parse_model_string("anthropic")


def test_parse_invalid_provider() -> None:
    with pytest.raises(ValueError, match="Provider desconhecido"):
        parse_model_string("azure:gpt-4")


# ---------------------------------------------------------------------------
# _build_effective_chain
# ---------------------------------------------------------------------------

def test_chain_primary_first() -> None:
    chain = _build_effective_chain(
        "ollama:qwen2.5:7b",
        ["ollama:qwen2.5:7b", "anthropic:claude-haiku-4-5"],
    )
    assert chain[0] == "ollama:qwen2.5:7b"
    assert chain[1] == "anthropic:claude-haiku-4-5"


def test_chain_deduplicates_primary() -> None:
    chain = _build_effective_chain(
        "anthropic:claude-haiku-4-5",
        ["anthropic:claude-haiku-4-5", "openai:gpt-4o-mini"],
    )
    assert chain.count("anthropic:claude-haiku-4-5") == 1


# ---------------------------------------------------------------------------
# Mock transport
# ---------------------------------------------------------------------------

class MockTransport:
    name = "mock"

    def __init__(
        self,
        *,
        response_text: str = "pong",
        raise_exc: Exception | None = None,
        tool_use: bool = True,
    ) -> None:
        self._response_text = response_text
        self._raise_exc = raise_exc
        self._caps = Capabilities(tool_use=tool_use, vision=False, json_mode=True, streaming=True, max_context=4096)
        self.call_count = 0

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    async def chat(self, messages, model, tools=None, stream=False, max_tokens=4096, **kw) -> ChatResponse:
        self.call_count += 1
        if self._raise_exc:
            raise self._raise_exc
        return ChatResponse(text=self._response_text, usage=Usage(input_tokens=10, output_tokens=5), model=model)

    async def stream(self, *a, **kw):
        return
        yield  # make it an async generator

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, latency_ms=1)

    async def get_model_capabilities(self, model_id: str) -> Capabilities:
        return self._caps


# ---------------------------------------------------------------------------
# ModelRouter — basic routing
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_with_mock() -> tuple[TransportRegistry, MockTransport]:
    mock = MockTransport()
    registry = TransportRegistry()
    registry.register("anthropic", lambda: mock)
    return registry, mock


@pytest.mark.asyncio
async def test_router_calls_correct_transport(registry_with_mock) -> None:
    registry, mock = registry_with_mock
    router = ModelRouter(registry=registry, default_model="anthropic:claude-haiku-4-5")

    resp = await router.chat(
        system="test",
        messages=[{"role": "user", "content": "ping"}],
        model="anthropic:claude-haiku-4-5",
    )
    assert resp.text == "pong"
    assert mock.call_count == 1


@pytest.mark.asyncio
async def test_router_uses_default_model_when_no_override(registry_with_mock) -> None:
    registry, mock = registry_with_mock
    router = ModelRouter(registry=registry, default_model="anthropic:claude-haiku-4-5")

    resp = await router.chat(system="test", messages=[{"role": "user", "content": "ping"}])
    assert resp.text == "pong"


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_triggered_on_connection_error() -> None:
    failing = MockTransport(raise_exc=ConnectionError("Ollama down"))
    fallback = MockTransport(response_text="fallback-response")

    registry = TransportRegistry()
    registry.register("ollama", lambda: failing)
    registry.register("anthropic", lambda: fallback)

    router = ModelRouter(
        registry=registry,
        default_model="ollama:qwen2.5:7b",
        fallback_chain=["ollama:qwen2.5:7b", "anthropic:claude-haiku-4-5"],
        timeout_s=5,
    )

    resp = await router.chat(system="test", messages=[{"role": "user", "content": "ping"}])
    assert resp.text == "fallback-response"
    assert fallback.call_count == 1


@pytest.mark.asyncio
async def test_fallback_NOT_triggered_on_rate_limit() -> None:
    """Rate limit é user error — não deve disparar fallback."""
    import anthropic as sdk
    import httpx

    fake_response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )
    failing = MockTransport(raise_exc=sdk.RateLimitError(
        "rate limited", response=fake_response, body={"error": {"type": "rate_limit_error"}}
    ))
    fallback = MockTransport()

    registry = TransportRegistry()
    registry.register("anthropic", lambda: failing)
    registry.register("ollama", lambda: fallback)

    router = ModelRouter(
        registry=registry,
        default_model="anthropic:claude-haiku-4-5",
        fallback_chain=["anthropic:claude-haiku-4-5", "ollama:qwen2.5:7b"],
        timeout_s=5,
    )

    with pytest.raises(sdk.RateLimitError):
        await router.chat(system="test", messages=[{"role": "user", "content": "ping"}])

    assert fallback.call_count == 0


# ---------------------------------------------------------------------------
# Capability check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capability_mismatch_raises_early() -> None:
    """Modelo sem tool_use com tools na chamada deve falhar antes de chamar a API."""
    no_tools_transport = MockTransport(tool_use=False)
    registry = TransportRegistry()
    registry.register("ollama", lambda: no_tools_transport)

    router = ModelRouter(registry=registry, default_model="ollama:gemma2:9b")

    with pytest.raises(CapabilityMismatchError, match="tool_use"):
        await router.chat(
            system="test",
            messages=[{"role": "user", "content": "ping"}],
            tools=[{"name": "dummy", "description": "x", "input_schema": {}}],
            model="ollama:gemma2:9b",
        )

    assert no_tools_transport.call_count == 0
