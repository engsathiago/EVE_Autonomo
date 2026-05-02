import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent.core import AIAgent
from agent.events import AgentEvent
from agent.tools.registry import ToolRegistry
from agent.transports.base import BaseTransport, ChatChunk, ChatResponse


class MockTransport(BaseTransport):
    """Transport configurável para testes."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def chat(self, system, messages, tools=None, max_tokens=4096) -> ChatResponse:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    def stream(self, system, messages, tools=None, max_tokens=4096) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError


def _resp(text: str, tool_calls: list[dict[str, Any]] | None = None) -> ChatResponse:
    return ChatResponse(
        text=text,
        tool_calls=tool_calls or [],
        raw={},
        usage={"input_tokens": 10, "output_tokens": 5},
    )


def _make_agent(responses: list[ChatResponse], registry: ToolRegistry | None = None) -> AIAgent:
    transport = MockTransport(responses)
    reg = registry or ToolRegistry()
    return AIAgent(transport=transport, tool_registry=reg)


# ── Loop básico ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_returns_text_without_tool_calls():
    agent = _make_agent([_resp("Olá, sou a Eve.")])
    result = await agent.run("diga olá")
    assert "Eve" in result.final_text
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_agent_tracks_tokens():
    agent = _make_agent([_resp("resposta")])
    result = await agent.run("pergunta")
    assert result.total_input_tokens == 10
    assert result.total_output_tokens == 5


@pytest.mark.asyncio
async def test_agent_calculates_duration():
    agent = _make_agent([_resp("ok")])
    result = await agent.run("go")
    assert result.duration_s >= 0


# ── Tool calls ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_executes_tool_and_continues():
    from agent.tools.base import BaseTool, ToolResult

    class PingTool(BaseTool):
        name = "ping"
        description = "ping"
        input_schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(ok=True, output="pong")

    registry = ToolRegistry()
    registry.register(PingTool())

    tool_call = {"id": "tc_1", "name": "ping", "input": {}}
    responses = [
        _resp("vou pingar", [tool_call]),
        _resp("pingado com sucesso"),
    ]
    agent = _make_agent(responses, registry)
    result = await agent.run("use ping")
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_agent_emits_events():
    events: list[AgentEvent] = []

    async def collect(e: AgentEvent) -> None:
        events.append(e)

    agent = _make_agent([_resp("pronto")])
    await agent.run("tarefa", on_event=collect)

    types = [e.type for e in events]
    assert "iteration_start" in types
    assert "planner_text" in types
    assert "done" in types


@pytest.mark.asyncio
async def test_agent_emits_tool_events():
    from agent.tools.base import BaseTool, ToolResult

    class EchoTool(BaseTool):
        name = "echo"
        description = "echo"
        input_schema: dict[str, Any] = {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
        }

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(ok=True, output=kwargs.get("msg"))

    registry = ToolRegistry()
    registry.register(EchoTool())

    events: list[AgentEvent] = []

    async def collect(e: AgentEvent) -> None:
        events.append(e)

    tool_call = {"id": "tc_2", "name": "echo", "input": {"msg": "hi"}}
    agent = _make_agent([_resp("chamando", [tool_call]), _resp("feito")], registry)
    await agent.run("echo hi", on_event=collect)

    types = [e.type for e in events]
    assert "tool_call" in types
    assert "tool_result" in types


# ── Limite de iterações ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_respects_max_iterations(monkeypatch):
    from agent.config import AgentSettings

    # Sempre retorna tool call → forçaria loop infinito sem o limite
    from agent.tools.base import BaseTool, ToolResult

    class LoopTool(BaseTool):
        name = "loop"
        description = "loop"
        input_schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(ok=True, output="still going")

    registry = ToolRegistry()
    registry.register(LoopTool())

    tool_call = {"id": "tc_x", "name": "loop", "input": {}}
    # Resposta infinita de tool calls
    transport = MockTransport([_resp("chamando", [tool_call])])
    settings = AgentSettings(max_iterations=3, reflection_every=10)
    agent = AIAgent(transport=transport, tool_registry=registry, settings=settings)

    result = await agent.run("loop forever")
    assert result.iterations <= 3


# ── Reflexão ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_reflection_done_exits_early():
    from agent.tools.base import BaseTool, ToolResult

    class NopTool(BaseTool):
        name = "nop"
        description = "nop"
        input_schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(ok=True, output="ok")

    registry = ToolRegistry()
    registry.register(NopTool())

    tool_call = {"id": "tc_r", "name": "nop", "input": {}}
    planner = MockTransport([_resp("executando", [tool_call])] * 10)
    reflector = MockTransport([
        ChatResponse(
            text=json.dumps({"progresso": "concluido", "problema": None, "ajuste_estrategia": None}),
            tool_calls=[],
            raw={},
            usage={"input_tokens": 5, "output_tokens": 5},
        )
    ])

    from agent.config import AgentSettings
    settings = AgentSettings(max_iterations=10, reflection_every=1)
    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
        settings=settings,
    )
    result = await agent.run("tarefa")
    # Deve sair antes do limite de 10 por causa do reflector "concluido"
    assert result.iterations < 5
