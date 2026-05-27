"""
Transport Ollama — usa a lib oficial 'ollama' (httpx internamente).
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agent.models.base import (
    Capabilities,
    CapabilityMismatchError,
    ChatResponse,
    HealthStatus,
    Message,
    ModelInfo,
    ModelNotPulledError,
    StreamChunk,
    ToolSchema,
    Usage,
)
from agent.models.capabilities import get_ollama_family_capabilities
from agent.observability.logger import get_logger

log = get_logger(__name__)


class OllamaTransport:
    """Transport Ollama — suporta tanto Ollama local quanto Ollama Cloud (ollama.com).

    Para Ollama Cloud, defina `api_key` (ou `OLLAMA_API_KEY` no .env) com a chave
    obtida em https://ollama.com/settings/keys. A `base_url` deve apontar para
    `https://ollama.com` ou o endpoint compatível do provider.
    """

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        api_key: str = "",
        timeout: int = 120,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

        # Header Authorization é adicionado apenas se api_key foi fornecida
        # (Ollama local não exige; Ollama Cloud exige Bearer token).
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
        )
        # cache: model_id → Capabilities
        self._caps_cache: dict[str, Capabilities] = {}

    @property
    def is_cloud(self) -> bool:
        """Retorna True se o transport está configurado para Ollama Cloud."""
        return bool(self._api_key)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            tool_use=False, vision=False, json_mode=False, streaming=True,
            max_context=32_768, parallel_tools=False,
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
        import json

        ollama_messages = [_to_ollama_message(m) for m in messages]
        tool_defs = [_to_ollama_tool(t) for t in (tools or [])]

        req: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tool_defs:
            req["tools"] = tool_defs

        log.info("ollama.chat.request", model=model, messages=len(ollama_messages))

        try:
            resp = await self._http.post("/api/chat", json=req)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(f"Ollama indisponível em {self._base_url}: {exc}") from exc

        if resp.status_code == 404:
            raise ModelNotPulledError(model)
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"Ollama Cloud rejeitou a requisição (HTTP {resp.status_code}). "
                "Verifique OLLAMA_API_KEY."
            )
        resp.raise_for_status()

        data = resp.json()
        msg = data.get("message", {})
        text = msg.get("content", "")

        tool_calls: list[dict[str, Any]] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append({
                "id": f"ollama-{i}",
                "name": fn.get("name", ""),
                "input": args,
            })

        usage = Usage(
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
        log.info(
            "ollama.chat.response",
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
        import json

        ollama_messages = [_to_ollama_message(m) for m in messages]
        req: dict[str, Any] = {
            "model": model,
            "messages": ollama_messages,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }

        try:
            async with self._http.stream("POST", "/api/chat", json=req) as resp:
                if resp.status_code == 404:
                    raise ModelNotPulledError(model)
                resp.raise_for_status()

                prompt_tokens = 0
                eval_tokens = 0
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        yield StreamChunk(type="text_delta", text=content)

                    if data.get("done"):
                        prompt_tokens = data.get("prompt_eval_count", 0)
                        eval_tokens = data.get("eval_count", 0)
                        yield StreamChunk(
                            type="message_end",
                            usage=Usage(input_tokens=prompt_tokens, output_tokens=eval_tokens),
                        )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(f"Ollama indisponível: {exc}") from exc

    # ------------------------------------------------------------------
    # capabilities discovery
    # ------------------------------------------------------------------

    async def get_model_capabilities(self, model_id: str) -> Capabilities:
        if model_id in self._caps_cache:
            return self._caps_cache[model_id]

        caps = await self._discover_capabilities(model_id)
        self._caps_cache[model_id] = caps
        return caps

    async def _discover_capabilities(self, model_id: str) -> Capabilities:
        try:
            resp = await self._http.post("/api/show", json={"model": model_id})
            if resp.status_code == 404:
                raise ModelNotPulledError(model_id)
            resp.raise_for_status()
            data = resp.json()
            caps_list: list[str] = data.get("capabilities") or []
            if caps_list:
                return Capabilities(
                    tool_use="tools" in caps_list,
                    vision="vision" in caps_list,
                    json_mode=True,
                    streaming=True,
                    max_context=_parse_context_length(data),
                    parallel_tools=False,
                )
        except ModelNotPulledError:
            raise
        except Exception as exc:
            log.debug("ollama.capabilities.discovery_failed", model=model_id, error=str(exc))

        # Fallback por família
        return get_ollama_family_capabilities(model_id)

    # ------------------------------------------------------------------
    # list_models / health
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self._http.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        result = []
        for m in data.get("models", []):
            model_id = m.get("name", "")
            caps = await self.get_model_capabilities(model_id)
            result.append(ModelInfo(
                provider="ollama",
                model_id=model_id,
                capabilities=caps,
                cost_input_per_1m=0.0,
                cost_output_per_1m=0.0,
            ))
        return result

    async def health(self) -> HealthStatus:
        t0 = time.monotonic()
        try:
            resp = await self._http.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            ms = int((time.monotonic() - t0) * 1000)
            models_loaded = len(data.get("models", []))
            return HealthStatus(ok=True, latency_ms=ms, models_loaded=models_loaded)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return HealthStatus(ok=False, message=f"Ollama não responde em {self._base_url}")
        except Exception as exc:
            return HealthStatus(ok=False, message=str(exc))


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _to_ollama_message(m: Message) -> dict[str, Any]:
    if isinstance(m.content, str):
        return {"role": m.role, "content": m.content}
    # Ollama não suporta content array — converte para string
    parts = []
    for block in m.content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return {"role": m.role, "content": "\n".join(parts)}


def _to_ollama_tool(t: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }


def _parse_context_length(show_data: dict[str, Any]) -> int:
    modelinfo = show_data.get("model_info", {})
    for key in ("llama.context_length", "context_length"):
        if key in modelinfo:
            return int(modelinfo[key])
    params = show_data.get("parameters", "")
    if "num_ctx" in str(params):
        for line in str(params).split("\n"):
            if "num_ctx" in line:
                try:
                    return int(line.split()[-1])
                except ValueError:
                    pass
    return 4096
