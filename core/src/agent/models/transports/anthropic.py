"""
Transport Anthropic — refatorado sobre o novo protocolo Transport.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import anthropic as sdk
import httpx

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
from agent.observability.logger import get_logger

log = get_logger(__name__)

_RETRYABLE_STATUSES = {503, 529}
_MAX_RETRIES = 3

_KNOWN_MODELS = [
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-7",
    "claude-opus-4-7",
]


class AnthropicTransport:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout: int = 120,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._client = sdk.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            tool_use=True,
            vision=True,
            json_mode=True,
            streaming=True,
            max_context=200_000,
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
        system, anthropic_messages = _split_system(messages)

        tool_defs = [_to_anthropic_tool(t) for t in (tools or [])]

        req: dict[str, Any] = dict(
            model=model,
            system=system,
            messages=anthropic_messages,
            max_tokens=max_tokens,
        )
        if tool_defs:
            req["tools"] = tool_defs

        log.info("anthropic.chat.request", model=model, messages=len(anthropic_messages))

        resp = await self._with_retry(lambda: self._client.messages.create(**req))

        text = ""
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": block.input})

        usage = Usage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )
        log.info(
            "anthropic.chat.response",
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_calls=len(tool_calls),
        )
        return ChatResponse(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            model=model,
            raw=resp.model_dump(),
        )

    # ------------------------------------------------------------------
    # stream
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        system, anthropic_messages = _split_system(messages)
        tool_defs = [_to_anthropic_tool(t) for t in (tools or [])]

        req: dict[str, Any] = dict(
            model=model,
            system=system,
            messages=anthropic_messages,
            max_tokens=max_tokens,
        )
        if tool_defs:
            req["tools"] = tool_defs

        async with self._client.messages.stream(**req) as s:
            current_tool: dict[str, Any] | None = None
            async for event in s:
                match event.type:
                    case "content_block_start":
                        if hasattr(event.content_block, "type"):
                            if event.content_block.type == "tool_use":
                                current_tool = {
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                }
                                yield StreamChunk(
                                    type="tool_use_start",
                                    tool_id=current_tool["id"],
                                    tool_name=current_tool["name"],
                                )
                    case "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamChunk(type="text_delta", text=delta.text)
                        elif delta.type == "input_json_delta" and current_tool:
                            yield StreamChunk(
                                type="tool_use_input",
                                partial_json=delta.partial_json,
                            )
                    case "content_block_stop":
                        if current_tool is not None:
                            yield StreamChunk(type="tool_use_end", tool_id=current_tool["id"])
                            current_tool = None
                    case "message_stop":
                        final = await s.get_final_message()
                        yield StreamChunk(
                            type="message_end",
                            usage=Usage(
                                input_tokens=final.usage.input_tokens,
                                output_tokens=final.usage.output_tokens,
                            ),
                        )

    # ------------------------------------------------------------------
    # list_models / health
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        result = []
        for model_id in _KNOWN_MODELS:
            alias = f"anthropic:{model_id}"
            caps = CLOUD_CAPABILITIES.get(alias, self.capabilities)
            from agent.models.pricing import PRICING_USD_PER_1M

            rates = PRICING_USD_PER_1M.get(alias, (0.0, 0.0))
            result.append(
                ModelInfo(
                    provider="anthropic",
                    model_id=model_id,
                    capabilities=caps,
                    cost_input_per_1m=rates[0],
                    cost_output_per_1m=rates[1],
                )
            )
        return result

    async def health(self) -> HealthStatus:
        import time

        if not self._api_key:
            return HealthStatus(ok=False, message="ANTHROPIC_API_KEY não configurada")
        t0 = time.monotonic()
        try:
            await self._client.models.list()
            ms = int((time.monotonic() - t0) * 1000)
            return HealthStatus(ok=True, latency_ms=ms)
        except sdk.AuthenticationError:
            return HealthStatus(ok=False, message="API key inválida")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))

    # ------------------------------------------------------------------
    # retry
    # ------------------------------------------------------------------

    async def _with_retry(self, fn: Any) -> Any:
        delay = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                return await fn()
            except sdk.RateLimitError:
                # Rate limit = user error; não retenta infinitamente — só re-raise
                raise
            except sdk.APIStatusError as exc:
                if exc.status_code not in _RETRYABLE_STATUSES or attempt == _MAX_RETRIES - 1:
                    raise
                log.warning("anthropic.retry", attempt=attempt + 1, delay=delay, status=exc.status_code)
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------


def _split_system(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Separa mensagem system (parâmetro top-level na API Anthropic) do array."""
    system = ""
    rest: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system = m.content if isinstance(m.content, str) else ""
        else:
            rest.append(_to_anthropic_message(m))
    return system, rest


def _to_anthropic_message(m: Message) -> dict[str, Any]:
    if isinstance(m.content, str):
        return {"role": m.role, "content": m.content}
    return {"role": m.role, "content": m.content}


def _to_anthropic_tool(t: ToolSchema) -> dict[str, Any]:
    return {
        "name": t.name,
        "description": t.description,
        "input_schema": t.input_schema,
    }
