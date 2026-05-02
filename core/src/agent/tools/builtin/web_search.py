from typing import Any

import httpx

from agent.config import get_settings
from agent.observability.logger import get_logger
from agent.tools.base import BaseTool, ToolResult

log = get_logger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT = 15.0


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Pesquisa na web. Use para informações atuais ou que você não tem certeza. "
        "Retorna título, URL e trecho de cada resultado."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Termos de busca"},
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "Número máximo de resultados (padrão 5)",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query: str = kwargs["query"]
        max_results: int = int(kwargs.get("max_results", 5))
        settings = get_settings()

        log.info("tool.web_search", query=query, provider=settings.search.provider)

        if settings.search.provider == "tavily" and settings.search.tavily_api_key:
            try:
                return await self._tavily(query, max_results, settings.search.tavily_api_key)
            except Exception as exc:
                log.warning("tool.web_search.tavily_failed", error=str(exc))
                # fallback para Brave

        if settings.search.brave_api_key:
            try:
                return await self._brave(query, max_results, settings.search.brave_api_key)
            except Exception as exc:
                log.error("tool.web_search.brave_failed", error=str(exc))
                return ToolResult(ok=False, error=f"Busca falhou: {exc}")

        return ToolResult(
            ok=False,
            error="Nenhum provider de busca configurado. Defina TAVILY_API_KEY ou BRAVE_API_KEY.",
        )

    async def _tavily(self, query: str, max_results: int, api_key: str) -> ToolResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _TAVILY_URL,
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "published_at": r.get("published_date"),
            }
            for r in data.get("results", [])
        ]
        log.info("tool.web_search.done", provider="tavily", count=len(results))
        return ToolResult(ok=True, output=results)

    async def _brave(self, query: str, max_results: int, api_key: str) -> ToolResult:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _BRAVE_URL,
                params={"q": query, "count": max_results},
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
                "published_at": None,
            }
            for r in data.get("web", {}).get("results", [])
        ]
        log.info("tool.web_search.done", provider="brave", count=len(results))
        return ToolResult(ok=True, output=results)
