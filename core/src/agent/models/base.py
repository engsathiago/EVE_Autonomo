"""
Protocolo unificado de transports. Todos os providers implementam essa interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Mensagem unificada
# ---------------------------------------------------------------------------


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]
    tool_call_id: str | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Schema de tool (subset do formato Anthropic/OpenAI)
# ---------------------------------------------------------------------------


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


# ---------------------------------------------------------------------------
# Uso de tokens
# ---------------------------------------------------------------------------


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


# ---------------------------------------------------------------------------
# Resposta de chat (unificada)
# ---------------------------------------------------------------------------


class ChatResponse(BaseModel):
    text: str
    tool_calls: list[dict[str, Any]] = []
    usage: Usage = Usage()
    model: str = ""
    raw: dict[str, Any] = {}
    # OpenRouter retorna custo direto no response
    openrouter_cost_usd: float | None = None


# ---------------------------------------------------------------------------
# Chunks de streaming
# ---------------------------------------------------------------------------


class StreamChunk(BaseModel):
    type: Literal[
        "text_delta",
        "tool_use_start",
        "tool_use_input",
        "tool_use_end",
        "message_end",
        "error",
    ]
    text: str | None = None
    tool_name: str | None = None
    tool_id: str | None = None
    partial_json: str | None = None
    usage: Usage | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Capabilities por modelo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capabilities:
    tool_use: bool = False
    vision: bool = False
    json_mode: bool = False
    streaming: bool = True
    max_context: int = 4096
    parallel_tools: bool = False


# ---------------------------------------------------------------------------
# Informação de modelo disponível
# ---------------------------------------------------------------------------


@dataclass
class ModelInfo:
    provider: str
    model_id: str
    capabilities: Capabilities
    cost_input_per_1m: float = 0.0
    cost_output_per_1m: float = 0.0

    @property
    def alias(self) -> str:
        return f"{self.provider}:{self.model_id}"


# ---------------------------------------------------------------------------
# Status de health
# ---------------------------------------------------------------------------


@dataclass
class HealthStatus:
    ok: bool
    latency_ms: int = 0
    message: str = ""
    models_loaded: int = 0


# ---------------------------------------------------------------------------
# Erros tipados
# ---------------------------------------------------------------------------


class ModelNotPulledError(Exception):
    """Modelo Ollama existe no registro mas não foi baixado localmente."""

    def __init__(self, model: str) -> None:
        super().__init__(f"Modelo Ollama '{model}' não encontrado. Execute: ollama pull {model}")
        self.model = model


class ModelNotFoundError(Exception):
    """Modelo não existe no provider."""

    def __init__(self, model: str, provider: str) -> None:
        super().__init__(f"Modelo '{model}' não encontrado no provider '{provider}'")
        self.model = model
        self.provider = provider


class CapabilityMismatchError(Exception):
    """Modelo não possui a capability exigida."""

    def __init__(self, model: str, required: str) -> None:
        super().__init__(
            f"Modelo '{model}' não suporta '{required}'. Escolha um modelo compatível ou remova o requisito."
        )
        self.model = model
        self.required = required


# ---------------------------------------------------------------------------
# Protocol Transport
# ---------------------------------------------------------------------------


@runtime_checkable
class Transport(Protocol):
    name: str
    capabilities: Capabilities

    async def chat(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        stream: bool = False,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ChatResponse: ...

    async def stream(
        self,
        messages: list[Message],
        model: str,
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]: ...

    async def list_models(self) -> list[ModelInfo]: ...

    async def health(self) -> HealthStatus: ...
