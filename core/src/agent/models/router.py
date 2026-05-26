"""
ModelRouter: resolve string 'provider:model', valida capabilities,
executa fallback chain e loga cada invocação em model_invocations.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent.models.base import (
    CapabilityMismatchError,
    ChatResponse,
    HealthStatus,
    Message,
    ModelInfo,
    ModelNotPulledError,
    ToolSchema,
)
from agent.models.capabilities import get_cloud_capabilities
from agent.models.pricing import cost_usd
from agent.models.registry import TransportRegistry
from agent.observability.logger import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

# Máximo de degraus no fallback para não cair em cascata
MAX_FALLBACK_DEPTH = 2

# Erros de infra que disparam fallback
_INFRA_EXCEPTION_TYPES = (
    ConnectionError,
    asyncio.TimeoutError,
    TimeoutError,
)

# Códigos HTTP que são erros de infra (provider indisponível)
_INFRA_HTTP_CODES = {500, 502, 503, 504, 529}

# Códigos HTTP que são erros de uso (não disparam fallback)
_USER_HTTP_CODES = {400, 401, 403, 422, 429}


def parse_model_string(s: str) -> tuple[str, str]:
    """'ollama:qwen2.5:32b' → ('ollama', 'qwen2.5:32b')"""
    provider, _, model = s.partition(":")
    if not provider or not model:
        raise ValueError(f"String de modelo inválida: {s!r}. Formato: 'provider:model'")
    allowed = {"anthropic", "openai", "openrouter", "ollama"}
    if provider not in allowed:
        raise ValueError(f"Provider desconhecido: {provider!r}. Permitidos: {allowed}")
    return provider, model


def _classify_exception(exc: Exception) -> str:
    """Classifica excepção para error_kind na tabela."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if "ratelimit" in name or "rate_limit" in name or "429" in msg:
        return "rate_limit"
    if "authentication" in name or "auth" in name or "401" in msg or "403" in msg:
        return "auth"
    if "timeout" in name or isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if "connect" in name or "connection" in name:
        return "timeout"
    if "notpulled" in name or "model_not_pulled" in name:
        return "model_not_pulled"
    if "capability" in name:
        return "capability_mismatch"
    if "invalidrequest" in name or "422" in msg or "400" in msg:
        return "invalid_request"
    if "503" in msg or "502" in msg or "500" in msg or "504" in msg:
        return "infra_error"
    return "unknown"


def _is_infra_error(exc: Exception) -> bool:
    """Retorna True se o erro justifica tentar o próximo da fallback chain."""
    if isinstance(exc, _INFRA_EXCEPTION_TYPES):
        return True
    if isinstance(exc, ModelNotPulledError):
        return True
    kind = _classify_exception(exc)
    return kind in {"timeout", "infra_error", "model_not_pulled"}


class ModelRouter:
    """
    Ponto central de chamadas LLM. Interface compatível com BaseTransport (duck typing).

    Expõe chat(system, messages, tools, max_tokens, *, model=None) para uso
    pelo AIAgent e SkillRunner sem quebrar a assinatura existente.
    """

    def __init__(
        self,
        registry: TransportRegistry,
        default_model: str = "anthropic:claude-sonnet-4-7",
        fallback_chain: list[str] | None = None,
        timeout_s: int = 60,
        db_pool: Any | None = None,
    ) -> None:
        self._registry = registry
        self._default_model = default_model
        self._fallback_chain = fallback_chain or []
        self._timeout_s = timeout_s
        self._db_pool = db_pool

    # ------------------------------------------------------------------
    # Interface compatível com BaseTransport (duck typing)
    # ------------------------------------------------------------------

    async def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
        session_id: str | None = None,
        skill_invocation_id: int | None = None,
    ) -> LegacyChatResponse:
        """Assinatura compatível com BaseTransport. Usa model= como override opcional."""
        from agent.transports.base import ChatResponse as LegacyResponse

        model_alias = model or self._default_model
        unified_msgs = _convert_legacy_messages(system, messages)
        unified_tools = _convert_legacy_tools(tools or [])

        response, fallback_info = await self._execute_with_fallback(
            model_alias=model_alias,
            messages=unified_msgs,
            tools=unified_tools if unified_tools else None,
            max_tokens=max_tokens,
        )

        await self._log_invocation(
            model_alias=model_alias,
            response=response,
            fallback_info=fallback_info,
            session_id=session_id,
            skill_invocation_id=skill_invocation_id,
        )

        # Converte de volta para o formato legado que AIAgent espera
        return LegacyResponse(
            text=response.text,
            tool_calls=response.tool_calls,
            raw=response.raw,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )

    # ------------------------------------------------------------------
    # API pública nova (para CLI e testes)
    # ------------------------------------------------------------------

    async def chat_unified(
        self,
        model_alias: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
        session_id: str | None = None,
        skill_invocation_id: int | None = None,
    ) -> ChatResponse:
        """API nova com tipos unificados. Usada pelos comandos CLI e testes."""
        response, fallback_info = await self._execute_with_fallback(
            model_alias=model_alias,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        await self._log_invocation(
            model_alias=model_alias,
            response=response,
            fallback_info=fallback_info,
            session_id=session_id,
            skill_invocation_id=skill_invocation_id,
        )
        return response

    # ------------------------------------------------------------------
    # Resolução e execução
    # ------------------------------------------------------------------

    async def _execute_with_fallback(
        self,
        model_alias: str,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        max_tokens: int,
    ) -> tuple[ChatResponse, dict[str, Any]]:
        chain = _build_effective_chain(model_alias, self._fallback_chain)
        fallback_info: dict[str, Any] = {"used": False, "from": None}
        last_exc: Exception | None = None

        for i, alias in enumerate(chain[: MAX_FALLBACK_DEPTH + 1]):
            if i > 0:
                log.warning(
                    "router.fallback",
                    original=chain[0],
                    current=alias,
                    reason=str(last_exc),
                )
                fallback_info = {"used": True, "from": chain[0]}

            provider, model_id = parse_model_string(alias)
            transport = self._registry.get(provider)

            # Valida capabilities antes de chamar a API
            caps = await self._get_capabilities(alias, provider, model_id, transport)
            if tools and not caps.tool_use:
                raise CapabilityMismatchError(alias, "tool_use")

            try:
                response = await asyncio.wait_for(
                    transport.chat(
                        messages=messages,
                        model=model_id,
                        tools=tools,
                        max_tokens=max_tokens,
                    ),
                    timeout=self._timeout_s,
                )
                response.model = alias
                return response, fallback_info

            except Exception as exc:
                last_exc = exc
                if not _is_infra_error(exc):
                    raise
                if i == len(chain) - 1 or i >= MAX_FALLBACK_DEPTH:
                    raise

        raise last_exc or RuntimeError("Fallback chain vazia")

    async def _get_capabilities(
        self,
        alias: str,
        provider: str,
        model_id: str,
        transport: Any,
    ) -> Any:
        if provider == "ollama":
            return await transport.get_model_capabilities(model_id)
        caps = get_cloud_capabilities(alias)
        return caps or transport.capabilities

    # ------------------------------------------------------------------
    # Logging no banco
    # ------------------------------------------------------------------

    async def _log_invocation(
        self,
        model_alias: str,
        response: ChatResponse,
        fallback_info: dict[str, Any],
        session_id: str | None,
        skill_invocation_id: int | None,
        started_at: float | None = None,
        latency_ms: int = 0,
        success: bool = True,
        error_kind: str | None = None,
        finished_at: float | None = None,
    ) -> None:
        if not self._db_pool:
            return

        provider, model_id = parse_model_string(response.model or model_alias)
        c = cost_usd(
            model_alias=response.model or model_alias,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            openrouter_cost=response.openrouter_cost_usd,
        )

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO model_invocations (
                        session_id, skill_invocation_id, provider, model, model_alias,
                        input_tokens, output_tokens, cost_usd, latency_ms,
                        success, error_kind, fallback_used, fallback_from, finished_at
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9,
                        $10, $11, $12, $13, NOW()
                    )
                    """,
                    session_id,
                    skill_invocation_id,
                    provider,
                    model_id,
                    response.model or model_alias,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    float(c),
                    latency_ms,
                    success,
                    error_kind,
                    fallback_info.get("used", False),
                    fallback_info.get("from"),
                )
        except Exception as exc:
            log.warning("router.log.failed", error=str(exc))

    # ------------------------------------------------------------------
    # Utilitários públicos
    # ------------------------------------------------------------------

    async def list_all_models(self) -> list[ModelInfo]:
        result: list[ModelInfo] = []
        for name in self._registry.available():
            try:
                transport = self._registry.get(name)
                result.extend(await transport.list_models())
            except Exception as exc:
                log.debug("router.list_models.failed", provider=name, error=str(exc))
        return result

    async def health_all(self) -> dict[str, HealthStatus]:
        return await self._registry.health_all()

    def default_model(self) -> str:
        return self._default_model


# ------------------------------------------------------------------
# helpers de conversão legado → unificado
# ------------------------------------------------------------------


def _convert_legacy_messages(system: str, messages: list[dict[str, Any]]) -> list[Message]:
    """Converte o formato dict legado (BaseTransport) para Message unificado."""
    result: list[Message] = []
    if system:
        result.append(Message(role="system", content=system))
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        result.append(Message(role=role, content=content))
    return result


def _convert_legacy_tools(tools: list[dict[str, Any]]) -> list[ToolSchema]:
    """Converte schemas de tool do formato Anthropic/legado para ToolSchema unificado."""
    result = []
    for t in tools:
        result.append(
            ToolSchema(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("input_schema", t.get("parameters", {})),
            )
        )
    return result


def _build_effective_chain(primary: str, chain: list[str]) -> list[str]:
    """Monta a chain de fallback com o modelo primário na frente."""
    rest = [m for m in chain if m != primary]
    return [primary] + rest


# Alias para type hints no AIAgent/SkillRunner
LegacyChatResponse = Any
