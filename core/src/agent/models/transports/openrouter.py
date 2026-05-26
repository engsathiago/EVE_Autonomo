"""
Transport OpenRouter — herda OpenAITransport, muda só base_url e headers obrigatórios.
"""

from __future__ import annotations

import httpx

from agent.models.base import Capabilities, HealthStatus, ModelInfo
from agent.models.transports.openai import OpenAITransport

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Subset representativo de modelos disponíveis no OpenRouter
_KNOWN_MODELS = [
    "anthropic/claude-3.5-sonnet",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemini-flash-1.5",
]


class OpenRouterTransport(OpenAITransport):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        http_referer: str = "https://github.com/agent",
        x_title: str = "agent",
        timeout: int = 120,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            timeout=timeout,
            http_client=http_client,
            extra_headers={
                "HTTP-Referer": http_referer,
                "X-Title": x_title,
            },
        )

    async def list_models(self) -> list[ModelInfo]:
        from agent.models.capabilities import CLOUD_CAPABILITIES

        result = []
        for model_id in _KNOWN_MODELS:
            alias = f"openrouter:{model_id}"
            caps = CLOUD_CAPABILITIES.get(
                alias,
                Capabilities(
                    tool_use=False,
                    vision=False,
                    json_mode=False,
                    streaming=True,
                    max_context=32_000,
                    parallel_tools=False,
                ),
            )
            result.append(
                ModelInfo(
                    provider="openrouter",
                    model_id=model_id,
                    capabilities=caps,
                    cost_input_per_1m=0.0,
                    cost_output_per_1m=0.0,
                )
            )
        return result

    async def health(self) -> HealthStatus:
        import time

        import openai

        if not self._api_key:
            return HealthStatus(ok=False, message="OPENROUTER_API_KEY não configurada")
        t0 = time.monotonic()
        try:
            await self._client.models.list()
            ms = int((time.monotonic() - t0) * 1000)
            return HealthStatus(ok=True, latency_ms=ms)
        except openai.AuthenticationError:
            return HealthStatus(ok=False, message="API key inválida")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))
