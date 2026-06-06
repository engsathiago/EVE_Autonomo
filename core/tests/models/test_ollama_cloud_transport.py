"""
Testes do OllamaCloudTransport — provider "ollama_cloud" separado do ollama local.

ZERO chamadas de rede reais — respx mocka todo tráfego HTTP.
Cobre os 5 cenários obrigatórios do B.1 + extras de cobertura.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from agent.models.base import Message
from agent.models.transports.ollama_cloud import OllamaCloudTransport

_CLOUD = "https://ollama.com"
_KEY = "sk-cloud-test-key"
_MODEL = "deepseek-v3.1:cloud"

_CHAT_200 = {
    "model": _MODEL,
    "message": {"role": "assistant", "content": "resposta ok"},
    "done": True,
    "prompt_eval_count": 10,
    "eval_count": 5,
}


def _transport() -> OllamaCloudTransport:
    return OllamaCloudTransport(base_url=_CLOUD, api_key=_KEY)


# ---------------------------------------------------------------------------
# 1. Happy path — 200 parseia corretamente em ChatResponse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_happy_path() -> None:
    """200 com payload Ollama válido → ChatResponse com text e usage populados."""
    respx.post(f"{_CLOUD}/api/chat").mock(return_value=httpx.Response(200, json=_CHAT_200))

    resp = await _transport().chat(
        messages=[Message(role="user", content="oi")],
        model=_MODEL,
    )

    assert resp.text == "resposta ok"
    assert resp.usage.input_tokens == 10
    assert resp.usage.output_tokens == 5
    assert resp.tool_calls == []


# ---------------------------------------------------------------------------
# 2. 401 → PermissionError — não é erro de infra, não dispara fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_auth_error_401() -> None:
    """401 deve levantar PermissionError — classificado como auth pelo router, sem fallback."""
    respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )

    with pytest.raises(PermissionError):
        await _transport().chat(
            messages=[Message(role="user", content="test")],
            model=_MODEL,
        )


@pytest.mark.asyncio
@respx.mock
async def test_auth_error_403() -> None:
    """403 também levanta PermissionError — mesmo tratamento que 401."""
    respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )

    with pytest.raises(PermissionError):
        await _transport().chat(
            messages=[Message(role="user", content="test")],
            model=_MODEL,
        )


# ---------------------------------------------------------------------------
# 3. 503 → httpx.HTTPStatusError — erro de infra, router encaminha para fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_infra_error_503() -> None:
    """503 → HTTPStatusError com status 503 — o router classifica como infra e faz fallback."""
    respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _transport().chat(
            messages=[Message(role="user", content="test")],
            model=_MODEL,
        )

    assert exc_info.value.response.status_code == 503


@pytest.mark.asyncio
@respx.mock
async def test_infra_error_502() -> None:
    """502 também é erro de infra."""
    respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(502, text="Bad Gateway")
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _transport().chat(
            messages=[Message(role="user", content="test")],
            model=_MODEL,
        )

    assert exc_info.value.response.status_code == 502


# ---------------------------------------------------------------------------
# 4. api_key ausente → ValueError na inicialização, mensagem clara
# ---------------------------------------------------------------------------


def test_missing_api_key_empty_string() -> None:
    """api_key='' deve levantar ValueError com menção a OLLAMA_CLOUD_API_KEY."""
    with pytest.raises(ValueError, match="OLLAMA_CLOUD_API_KEY"):
        OllamaCloudTransport(base_url=_CLOUD, api_key="")


def test_missing_api_key_default() -> None:
    """Instanciar sem args usa api_key='' (default) → ValueError."""
    with pytest.raises(ValueError):
        OllamaCloudTransport()


# ---------------------------------------------------------------------------
# 5. Authorization header enviado em todas as requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_authorization_header_set_on_chat() -> None:
    """Header 'Authorization: Bearer <key>' enviado em toda chamada chat()."""
    route = respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(200, json=_CHAT_200)
    )

    await _transport().chat(
        messages=[Message(role="user", content="ping")],
        model=_MODEL,
    )

    assert route.called
    sent = route.calls[0].request.headers.get("authorization")
    assert sent == f"Bearer {_KEY}", f"Authorization incorreto: {sent!r}"


@pytest.mark.asyncio
@respx.mock
async def test_authorization_header_set_on_health() -> None:
    """Header Authorization também presente no health check."""
    route = respx.get(f"{_CLOUD}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": _MODEL}]})
    )

    status = await _transport().health()

    assert status.ok
    sent = route.calls[0].request.headers.get("authorization")
    assert sent == f"Bearer {_KEY}"


# ---------------------------------------------------------------------------
# Extras: name, provider, injeção de http_client customizado
# ---------------------------------------------------------------------------


def test_transport_name() -> None:
    """name deve ser 'ollama_cloud' para o router resolver provider corretamente."""
    assert _transport().name == "ollama_cloud"


@pytest.mark.asyncio
@respx.mock
async def test_list_models_returns_ollama_cloud_provider() -> None:
    """list_models() retorna ModelInfo com provider='ollama_cloud', não 'ollama'."""
    respx.get(f"{_CLOUD}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": _MODEL}]})
    )
    # get_model_capabilities chama /api/show
    respx.post(f"{_CLOUD}/api/show").mock(
        return_value=httpx.Response(200, json={"capabilities": ["tools"]})
    )

    models = await _transport().list_models()

    assert len(models) == 1
    assert models[0].provider == "ollama_cloud"
    assert models[0].model_id == _MODEL


def test_injected_http_client_takes_precedence() -> None:
    """http_client injetado é usado no lugar do criado internamente."""
    custom = httpx.AsyncClient(base_url=_CLOUD)
    t = OllamaCloudTransport(base_url=_CLOUD, api_key=_KEY, http_client=custom)
    assert t._http is custom
