from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel


class ChatChunk(BaseModel):
    type: Literal[
        "text", "tool_call_start", "tool_call_delta", "tool_call_end", "done"
    ]
    text: str | None = None
    tool_call: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    text: str
    tool_calls: list[dict[str, Any]]
    raw: dict[str, Any]
    usage: dict[str, int]  # input_tokens, output_tokens


class BaseTransport(ABC):
    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> ChatResponse: ...

    @abstractmethod
    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[ChatChunk]: ...
