import json
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import __version__
from agent.config import get_settings
from agent.core import AIAgent
from agent.events import AgentEvent
from agent.observability import configure_logging
from agent.tools.registry import ToolRegistry, register_builtin
from agent.transports import AnthropicTransport

app = FastAPI(title="agent-core", version=__version__)

# Inicializa infra no startup
_registry: ToolRegistry | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _registry
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    _registry = ToolRegistry()
    register_builtin(_registry)


def _get_registry() -> ToolRegistry:
    if _registry is None:
        raise RuntimeError("registry não inicializado")
    return _registry


# ── Request/Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    text: str
    iterations: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    duration_s: float


class ToolInfo(BaseModel):
    name: str
    description: str
    requires_confirmation: bool


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "ok": True,
        "version": __version__,
        "model": settings.agent.default_model,
    }


@app.get("/api/tools")
async def list_tools() -> dict[str, object]:
    registry = _get_registry()
    tools = []
    for name in registry.names():
        tool = registry.get(name)
        if tool:
            tools.append(ToolInfo(
                name=tool.name,
                description=tool.description,
                requires_confirmation=tool.requires_confirmation,
            ))
    return {"tools": [t.model_dump() for t in tools]}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=_get_registry(),
        reflector_transport=reflector,
    )
    result = await agent.run(goal=req.message)

    return ChatResponse(
        text=result.final_text,
        iterations=result.iterations,
        input_tokens=result.total_input_tokens,
        output_tokens=result.total_output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        duration_s=result.duration_s,
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    settings = get_settings()
    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=_get_registry(),
        reflector_transport=reflector,
    )

    async def _event_stream() -> AsyncGenerator[str, None]:
        # Coleta eventos em fila para streaming correto
        import asyncio
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def enqueue(event: AgentEvent) -> None:
            await queue.put(event)

        async def run_agent() -> None:
            await agent.run(goal=req.message, on_event=enqueue)
            await queue.put(None)  # sentinel

        task = asyncio.create_task(run_agent())

        while True:
            event = await queue.get()
            if event is None:
                break
            data = json.dumps(event.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"

        await task

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
