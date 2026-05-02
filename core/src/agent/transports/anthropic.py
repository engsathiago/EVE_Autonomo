import asyncio
from collections.abc import AsyncIterator
from typing import Any

import anthropic as sdk

from agent.config import get_settings
from agent.observability.logger import get_logger
from agent.transports.base import BaseTransport, ChatChunk, ChatResponse

log = get_logger(__name__)

_RETRYABLE = {429, 503, 529}
_MAX_RETRIES = 3


class AnthropicTransport(BaseTransport):
    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self._model = model or settings.anthropic.planner_model
        self._client = sdk.AsyncAnthropic(
            api_key=settings.anthropic.api_key,
            base_url=settings.anthropic.base_url,
            timeout=settings.anthropic.timeout,
            max_retries=0,  # retry manual para logar tentativas
        )

    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        log.info(
            "transport.request",
            model=self._model,
            messages=len(messages),
            tools=len(tools or []),
        )

        kwargs: dict[str, Any] = dict(
            model=self._model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        resp = await self._with_retry(lambda: self._client.messages.create(**kwargs))

        text = ""
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {"id": block.id, "name": block.name, "input": block.input}
                )

        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
        log.info(
            "transport.response",
            model=self._model,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            tool_calls=len(tool_calls),
        )
        return ChatResponse(
            text=text, tool_calls=tool_calls, raw=resp.model_dump(), usage=usage
        )

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[ChatChunk]:
        log.info(
            "transport.stream.start",
            model=self._model,
            messages=len(messages),
        )
        kwargs: dict[str, Any] = dict(
            model=self._model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            current_tool: dict[str, Any] | None = None
            async for event in stream:
                match event.type:
                    case "content_block_start":
                        if hasattr(event.content_block, "type"):
                            if event.content_block.type == "tool_use":
                                current_tool = {
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input": "",
                                }
                                yield ChatChunk(
                                    type="tool_call_start",
                                    tool_call=dict(current_tool),
                                )
                    case "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield ChatChunk(type="text", text=delta.text)
                        elif delta.type == "input_json_delta" and current_tool:
                            current_tool["input"] += delta.partial_json
                            yield ChatChunk(
                                type="tool_call_delta",
                                tool_call={"partial_json": delta.partial_json},
                            )
                    case "content_block_stop":
                        if current_tool is not None:
                            yield ChatChunk(
                                type="tool_call_end",
                                tool_call=dict(current_tool),
                            )
                            current_tool = None
                    case "message_stop":
                        yield ChatChunk(type="done")

    async def _with_retry(self, fn: Any) -> Any:
        delay = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                return await fn()
            except sdk.RateLimitError:
                if attempt == _MAX_RETRIES - 1:
                    raise
                log.warning(
                    "transport.retry",
                    attempt=attempt + 1,
                    delay=delay,
                    reason="rate_limit",
                )
                await asyncio.sleep(delay)
                delay *= 2
            except sdk.APIStatusError as e:
                if e.status_code not in _RETRYABLE or attempt == _MAX_RETRIES - 1:
                    raise
                log.warning(
                    "transport.retry",
                    attempt=attempt + 1,
                    delay=delay,
                    status=e.status_code,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")
