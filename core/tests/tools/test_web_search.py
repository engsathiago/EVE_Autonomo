import pytest
import respx
import httpx

from agent.tools.builtin.web_search import WebSearchTool, _TAVILY_URL, _BRAVE_URL


def _mock_settings(provider="tavily", tavily_key="fake-key", brave_key=""):
    return type("S", (), {
        "search": type("Srch", (), {
            "provider": provider,
            "tavily_api_key": tavily_key,
            "brave_api_key": brave_key,
        })(),
    })()


@pytest.mark.asyncio
@respx.mock
async def test_tavily_search_ok(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.builtin.web_search.get_settings",
        lambda: _mock_settings(),
    )
    respx.post(_TAVILY_URL).mock(return_value=httpx.Response(200, json={
        "results": [
            {"title": "Python docs", "url": "https://python.org", "content": "Official Python"},
        ]
    }))
    result = await WebSearchTool().execute(query="python", max_results=1)
    assert result.ok
    assert len(result.output) == 1
    assert result.output[0]["title"] == "Python docs"


@pytest.mark.asyncio
@respx.mock
async def test_tavily_fallback_to_brave(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.builtin.web_search.get_settings",
        lambda: _mock_settings(tavily_key="key", brave_key="brave-key"),
    )
    # Tavily falha
    respx.post(_TAVILY_URL).mock(side_effect=httpx.ConnectError("down"))
    # Brave funciona
    respx.get(_BRAVE_URL).mock(return_value=httpx.Response(200, json={
        "web": {"results": [{"title": "Brave result", "url": "https://brave.com", "description": "x"}]}
    }))
    result = await WebSearchTool().execute(query="test")
    assert result.ok
    assert result.output[0]["title"] == "Brave result"


@pytest.mark.asyncio
async def test_no_provider_configured(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.builtin.web_search.get_settings",
        lambda: _mock_settings(tavily_key="", brave_key=""),
    )
    result = await WebSearchTool().execute(query="test")
    assert not result.ok
    assert "Nenhum provider" in result.error


@pytest.mark.asyncio
@respx.mock
async def test_tavily_http_error(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.builtin.web_search.get_settings",
        lambda: _mock_settings(tavily_key="key", brave_key=""),
    )
    respx.post(_TAVILY_URL).mock(return_value=httpx.Response(401))
    result = await WebSearchTool().execute(query="test")
    assert not result.ok
