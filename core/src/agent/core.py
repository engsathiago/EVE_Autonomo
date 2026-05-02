import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from agent.config import AgentSettings, get_settings
from agent.events import AgentEvent
from agent.observability.logger import get_logger
from agent.prompts.system import PLANNER_SYSTEM, REFLECTOR_SYSTEM
from agent.tools.registry import ToolRegistry
from agent.transports.base import BaseTransport

log = get_logger(__name__)

OnEvent = Callable[[AgentEvent], Awaitable[None]]

# Custo aproximado por 1M tokens (USD) — usado só para estimativa no display
_COST_PER_1M = {"claude-haiku-4-5": 0.80, "claude-sonnet-4-6": 3.00}


class AgentResult(BaseModel):
    final_text: str
    iterations: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    duration_s: float


class AIAgent:
    def __init__(
        self,
        transport: BaseTransport,
        tool_registry: ToolRegistry,
        reflector_transport: BaseTransport | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        self._transport = transport
        self._registry = tool_registry
        self._reflector = reflector_transport
        self._settings = settings or get_settings().agent

    async def run(
        self,
        goal: str,
        on_event: OnEvent | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        start = time.monotonic()
        messages: list[dict[str, Any]] = list(conversation_history or [])
        messages.append({"role": "user", "content": goal})

        tools = self._registry.all_schemas()
        total_in = total_out = 0
        model = self._settings.default_model
        last_text = ""  # rastreia o último texto do planner

        async def emit(event: AgentEvent) -> None:
            if on_event:
                await on_event(event)

        for iteration in range(1, self._settings.max_iterations + 1):
            await emit(AgentEvent(type="iteration_start", data={"iteration": iteration}))
            log.info("agent.iteration", iteration=iteration)

            # ── Plan + Act ──────────────────────────────────────────────────
            response = await self._transport.chat(
                system=PLANNER_SYSTEM,
                messages=messages,
                tools=tools or None,
                max_tokens=4096,
            )
            total_in += response.usage["input_tokens"]
            total_out += response.usage["output_tokens"]

            if response.text:
                last_text = response.text
                await emit(AgentEvent(type="planner_text", data={"text": response.text}))

            # Sem tool calls → agente concluiu
            if not response.tool_calls:
                log.info("agent.done", iteration=iteration, reason="no_tool_calls")
                await emit(
                    AgentEvent(
                        type="done",
                        data={"text": response.text, "iteration": iteration},
                    )
                )
                break

            # Adiciona resposta do assistente ao histórico
            messages.append(self._build_assistant_message(response.text, response.tool_calls))

            # ── Execute tools ───────────────────────────────────────────────
            tool_results = await self._execute_tools(response.tool_calls, emit)
            messages.append({"role": "user", "content": tool_results})

            # ── Reflection ──────────────────────────────────────────────────
            if (
                self._reflector is not None
                and iteration % self._settings.reflection_every == 0
            ):
                hint = await self._reflect(messages)
                if hint:
                    if hint.get("progresso") == "concluido":
                        log.info("agent.done", iteration=iteration, reason="reflector_done")
                        await emit(AgentEvent(type="done", data={"iteration": iteration}))
                        break
                    if hint.get("progresso") == "estagnado" and hint.get("ajuste_estrategia"):
                        messages.append({
                            "role": "user",
                            "content": (
                                f"[Reflexão do sistema]: {hint['ajuste_estrategia']}"
                            ),
                        })
                        await emit(
                            AgentEvent(type="reflection", data=hint)
                        )
        else:
            # Limite de iterações atingido
            log.warning("agent.max_iterations", limit=self._settings.max_iterations)
            await emit(
                AgentEvent(
                    type="done",
                    data={"text": "Limite de iterações atingido.", "iteration": iteration},
                )
            )

        final_text = last_text or self._extract_final_text(messages)
        duration = time.monotonic() - start
        cost = self._estimate_cost(model, total_in, total_out)

        log.info(
            "agent.result",
            iterations=iteration,
            input_tokens=total_in,
            output_tokens=total_out,
            cost_usd=cost,
            duration_s=round(duration, 2),
        )

        return AgentResult(
            final_text=final_text,
            iterations=iteration,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            estimated_cost_usd=cost,
            duration_s=round(duration, 2),
        )

    async def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        emit: Callable[[AgentEvent], Awaitable[None]],
    ) -> list[dict[str, Any]]:
        async def _run_one(call: dict[str, Any]) -> dict[str, Any]:
            name = call["name"]
            args = call.get("input", {})
            tool = self._registry.get(name)

            await emit(
                AgentEvent(
                    type="tool_call",
                    data={
                        "id": call["id"],
                        "name": name,
                        "args": args,
                        "requires_confirmation": (
                            tool.requires_confirmation if tool else False
                        ),
                    },
                )
            )

            result = await self._registry.execute(name, args)

            await emit(
                AgentEvent(
                    type="tool_result",
                    data={"id": call["id"], "name": name, "ok": result.ok, "output": result.output},
                )
            )

            return {
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": (
                    json.dumps(result.output, ensure_ascii=False)
                    if result.ok
                    else f"ERROR: {result.error}"
                ),
            }

        results = await asyncio.gather(*[_run_one(c) for c in tool_calls])
        return list(results)

    async def _reflect(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self._reflector is None:
            return None
        try:
            resp = await self._reflector.chat(
                system=REFLECTOR_SYSTEM,
                messages=messages,
                max_tokens=512,
            )
            parsed: dict[str, Any] = json.loads(resp.text)
            return parsed
        except Exception as exc:
            log.warning("agent.reflection.failed", error=str(exc))
            return None

    @staticmethod
    def _build_assistant_message(
        text: str, tool_calls: list[dict[str, Any]]
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for call in tool_calls:
            content.append({
                "type": "tool_use",
                "id": call["id"],
                "name": call["name"],
                "input": call.get("input", {}),
            })
        return {"role": "assistant", "content": content}

    @staticmethod
    def _extract_final_text(messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return str(block.get("text", ""))
        return ""

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        rate = _COST_PER_1M.get(model, 1.0)
        return round((input_tokens + output_tokens) / 1_000_000 * rate, 6)
