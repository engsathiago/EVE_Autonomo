"""
Transport OpenAI. Também usado como base para OpenRouter.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai

from agent.models.base import (
    Capabilities,
    ChatResponse,
    HealthStatus,
    Message,
    ModelInfo,
    StreamChunk,
    ToolSchema,
    Usage,
)
from agent.models.capabilities import CLOUD_CAPABILITIES
from agent.models.pricing import PRICING_USD_PER_1M
from agent.observability.logger import get_logger

log = get_logger(__name__)

_KNOWN_MODELS = ["gpt-4o", "gpt-4o-mini"]


class OpenAITransport:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 120,
        http_client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._extra_headers = extra_headers or {}
        # SDK 2.x recusa construção com key vazia — usa placeholder para diferir o erro para health()
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "placeholder-not-configured",
            base_url=base_url,
            timeout=timeout,
            http_client=http_client,
            default_headers=self._extra_headers,
        )

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            tool_use=True,
            vision=True,
            json_mode=True,
            streaming=True,
            max_context=128_000,
            parallel_tools=True,
        )

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        stream: bool = False,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ChatResponse:
        oai_messages = [_to_openai_message(m) for m in messages]
        tool_defs = [_to_openai_tool(t) for t in (tools or [])]

        req: dict[str, Any] = dict(
            model=model,
            messages=oai_messages,
            max_tokens=max_tokens,
        )
        if tool_defs:
            req["tools"] = tool_defs

        log.info("openai.chat.request", model=model, provider=self.name, messages=len(oai_messages))
        resp = await self._client.chat.completions.create(**req)

        choice = resp.choices[0]
        text = choice.message.content or ""
        tool_calls: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json

                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments or "{}"),
                    }
                )

        usage = Usage(
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

        # OpenRouter retorna custo em usage.cost (campo não-padrão)
        openrouter_cost: float | None = None
        if hasattr(resp, "usage") and resp.usage and hasattr(resp.usage, "cost"):
            openrouter_cost = float(resp.usage.cost)  # type: ignore[attr-defined]

        log.info(
            "openai.chat.response",
            model=model,
            provider=self.name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            openrouter_cost_usd=openrouter_cost,
        )

    # ------------------------------------------------------------------
    # stream (não usada pela CLI na F4, mas implementada para F7)
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        oai_messages = [_to_openai_message(m) for m in messages]
        tool_defs = [_to_openai_tool(t) for t in (tools or [])]

        req: dict[str, Any] = dict(
            model=model,
            messages=oai_messages,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tool_defs:
            req["tools"] = tool_defs

        current_tool_id: str | None = None
        current_tool_name: str | None = None

        async with await self._client.chat.completions.create(**req) as s:
            async for chunk in s:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta

                if delta.content:
                    yield StreamChunk(type="text_delta", text=delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.id:
                            if current_tool_id:
                                yield StreamChunk(type="tool_use_end", tool_id=current_tool_id)
                            current_tool_id = tc.id
                            current_tool_name = tc.function.name if tc.function else ""
                            yield StreamChunk(
                                type="tool_use_start",
                                tool_id=current_tool_id,
                                tool_name=current_tool_name,
                            )
                        elif tc.function and tc.function.arguments:
                            yield StreamChunk(
                                type="tool_use_input",
                                partial_json=tc.function.arguments,
                            )

                if choice.finish_reason == "tool_calls" and current_tool_id:
                    yield StreamChunk(type="tool_use_end", tool_id=current_tool_id)
                    current_tool_id = None

                if chunk.usage:
                    yield StreamChunk(
                        type="message_end",
                        usage=Usage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                        ),
                    )

    # ------------------------------------------------------------------
    # list_models / health
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        result = []
        for model_id in _KNOWN_MODELS:
            alias = f"{self.name}:{model_id}"
            caps = CLOUD_CAPABILITIES.get(alias, self.capabilities)
            rates = PRICING_USD_PER_1M.get(alias, (0.0, 0.0))
            result.append(
                ModelInfo(
                    provider=self.name,
                    model_id=model_id,
                    capabilities=caps,
                    cost_input_per_1m=rates[0],
                    cost_output_per_1m=rates[1],
                )
            )
        return result

    async def health(self) -> HealthStatus:
        if not self._api_key:
            return HealthStatus(ok=False, message=f"{self.name.upper()}_API_KEY não configurada")
        t0 = time.monotonic()
        try:
            await self._client.models.list()
            ms = int((time.monotonic() - t0) * 1000)
            return HealthStatus(ok=True, latency_ms=ms)
        except openai.AuthenticationError:
            return HealthStatus(ok=False, message="API key inválida")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------


def _to_openai_message(m: Message) -> dict[str, Any]:
    base: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id:
        base["tool_call_id"] = m.tool_call_id
    if m.name:
        base["name"] = m.name
    return base


def _to_openai_tool(t: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }
