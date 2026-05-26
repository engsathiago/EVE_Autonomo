"""
Testes do OllamaTransport com suporte a Ollama Cloud (api_key + Bearer token)
e dos env var overrides para modelos de missões.
Usa respx para mock HTTP — não exige Ollama nem conectividade real.
"""
from __future__ import annotations

import pytest
import respx
import httpx

from agent.models.base import Message
from agent.models.transports.ollama import OllamaTransport

_LOCAL = "http://localhost:11434"
_CLOUD = "https://ollama.com"
_KEY   = "sk-ollama-test-key"


# ---------------------------------------------------------------------------
# _build_headers — comportamento sem e com api_key
# ---------------------------------------------------------------------------

def test_build_headers_without_api_key_returns_empty() -> None:
    t = OllamaTransport(base_url=_LOCAL)
    assert t._build_headers() == {}


def test_build_headers_with_api_key_returns_bearer() -> None:
    t = OllamaTransport(base_url=_CLOUD, api_key=_KEY)
    assert t._build_headers() == {"Authorization": f"Bearer {_KEY}"}


def test_build_headers_empty_string_treated_as_no_key() -> None:
    t = OllamaTransport(base_url=_LOCAL, api_key="")
    assert t._build_headers() == {}


# ---------------------------------------------------------------------------
# __init__ — api_key preserva comportamento local intacto
# ---------------------------------------------------------------------------

def test_init_without_api_key_creates_client_without_auth() -> None:
    t = OllamaTransport(base_url=_LOCAL)
    assert t._api_key is None
    assert "Authorization" not in t._http.headers


def test_init_with_api_key_sets_bearer_header_on_client() -> None:
    t = OllamaTransport(base_url=_CLOUD, api_key=_KEY)
    assert t._api_key == _KEY
    assert t._http.headers.get("authorization") == f"Bearer {_KEY}"


def test_init_injected_http_client_takes_precedence() -> None:
    custom = httpx.AsyncClient(base_url=_LOCAL)
    t = OllamaTransport(base_url=_LOCAL, api_key=_KEY, http_client=custom)
    assert t._http is custom


# ---------------------------------------------------------------------------
# chat() — header Authorization enviado quando api_key presente
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_chat_cloud_sends_authorization_header() -> None:
    route = respx.post(f"{_CLOUD}/api/chat").mock(
        return_value=httpx.Response(200, json={
            "model": "gpt-oss:120b-cloud",
            "message": {"role": "assistant", "content": "pong"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 4,
        })
    )
    t = OllamaTransport(base_url=_CLOUD, api_key=_KEY)
    resp = await t.chat(
        messages=[Message(role="user", content="ping")],
        model="gpt-oss:120b-cloud",
    )
    assert resp.text == "pong"
    assert route.called
    sent_auth = route.calls[0].request.headers.get("authorization")
    assert sent_auth == f"Bearer {_KEY}", f"Authorization ausente ou errado: {sent_auth!r}"


@pytest.mark.asyncio
@respx.mock
async def test_chat_local_no_authorization_header() -> None:
    route = respx.post(f"{_LOCAL}/api/chat").mock(
        return_value=httpx.Response(200, json={
            "model": "qwen2.5:7b",
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 3,
        })
    )
    t = OllamaTransport(base_url=_LOCAL)
    await t.chat(messages=[Message(role="user", content="hi")], model="qwen2.5:7b")
    assert route.called
    sent_auth = route.calls[0].request.headers.get("authorization")
    assert sent_auth is None, f"Authorization não deveria estar presente: {sent_auth!r}"


# ---------------------------------------------------------------------------
# health() — cloud também envia Bearer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_health_cloud_sends_authorization_header() -> None:
    route = respx.get(f"{_CLOUD}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "gpt-oss:120b-cloud"}]})
    )
    t = OllamaTransport(base_url=_CLOUD, api_key=_KEY)
    status = await t.health()
    assert status.ok
    sent_auth = route.calls[0].request.headers.get("authorization")
    assert sent_auth == f"Bearer {_KEY}"


# ---------------------------------------------------------------------------
# Env var overrides para modelos de missões (MISSIONS_PLANNER_MODEL etc.)
# ---------------------------------------------------------------------------

def test_missions_planner_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """MISSIONS_PLANNER_MODEL sobrescreve config.yaml."""
    monkeypatch.setenv("MISSIONS_PLANNER_MODEL", "ollama:qwen3-coder:480b-cloud")
    from agent.config import Settings
    s = Settings.from_yaml()
    assert s.missions.planner_model == "ollama:qwen3-coder:480b-cloud"


def test_missions_reflector_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """MISSIONS_REFLECTOR_MODEL sobrescreve config.yaml."""
    monkeypatch.setenv("MISSIONS_REFLECTOR_MODEL", "ollama:qwen3-coder:480b-cloud")
    from agent.config import Settings
    s = Settings.from_yaml()
    assert s.missions.reflector_model == "ollama:qwen3-coder:480b-cloud"


def test_missions_models_fall_back_to_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem env var, usa valores do config.yaml (Anthropic por padrão)."""
    monkeypatch.delenv("MISSIONS_PLANNER_MODEL", raising=False)
    monkeypatch.delenv("MISSIONS_REFLECTOR_MODEL", raising=False)
    from agent.config import Settings
    s = Settings.from_yaml()
    assert s.missions.planner_model.startswith("anthropic:")
    assert s.missions.reflector_model.startswith("anthropic:")


def test_missions_env_override_empty_string_falls_back_to_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """String vazia na env var não deve sobrescrever — usa config.yaml."""
    monkeypatch.setenv("MISSIONS_PLANNER_MODEL", "")
    from agent.config import Settings
    s = Settings.from_yaml()
    assert s.missions.planner_model.startswith("anthropic:")
