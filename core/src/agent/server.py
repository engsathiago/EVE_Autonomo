import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import __version__
from agent.config import get_settings
from agent.core import AIAgent
from agent.events import AgentEvent
from agent.memory.compressor import ContextCompressor
from agent.memory.curator import Curator
from agent.memory.store import MemoryStore
from agent.observability import configure_logging
from agent.skills.manager import SkillManager
from agent.tools.registry import ToolRegistry, register_builtin, register_memory_tools
from agent.transports import AnthropicTransport

app = FastAPI(title="agent-core", version=__version__)

_registry: ToolRegistry | None = None
_memory_store: MemoryStore | None = None
_curator: Curator | None = None
_compressor: ContextCompressor | None = None
_skill_manager: SkillManager | None = None

_CURATOR_ENABLED = os.getenv("MEMORY_CURATOR_ENABLED", "true").lower() != "false"


@app.on_event("startup")
async def _startup() -> None:
    global _registry, _memory_store, _curator, _compressor, _skill_manager
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    _memory_store = await MemoryStore.create()
    _curator = Curator() if _CURATOR_ENABLED else None
    _compressor = ContextCompressor()

    _registry = ToolRegistry()
    register_builtin(_registry)
    register_memory_tools(_registry, _memory_store)

    _skill_manager = SkillManager(
        skills_dir=Path(settings.skills.skills_dir),
        transport=AnthropicTransport(model=settings.anthropic.planner_model),
        memory_store=_memory_store,
        cache_dir=Path(settings.skills.skills_embedding_cache_dir),
    )
    await _skill_manager.load_all()


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _memory_store:
        await _memory_store.close()


def _get_registry() -> ToolRegistry:
    if _registry is None:
        raise RuntimeError("registry não inicializado")
    return _registry


def _get_store() -> MemoryStore:
    if _memory_store is None:
        raise RuntimeError("memory_store não inicializado")
    return _memory_store


def _get_skill_manager() -> SkillManager:
    if _skill_manager is None:
        raise RuntimeError("skill_manager não inicializado")
    return _skill_manager


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
    conversation_id: str


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
    store = _get_store()

    # Resolve ou cria conversation
    if req.conversation_id:
        conversation_id = UUID(req.conversation_id)
        history_rows = await store.get_messages(conversation_id, limit=50)
        conversation_history = _rows_to_messages(history_rows)
    else:
        conversation_id = await store.create_conversation()
        conversation_history = []

    # Cria registry com as memory tools vinculadas a esta conversa
    registry = ToolRegistry()
    register_builtin(registry)
    register_memory_tools(registry, store, conversation_id)

    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
        memory_store=store,
        curator=_curator,
        compressor=_compressor,
        conversation_id=conversation_id,
        skill_manager=_get_skill_manager(),
    )
    result = await agent.run(goal=req.message, conversation_history=conversation_history)

    return ChatResponse(
        text=result.final_text,
        iterations=result.iterations,
        input_tokens=result.total_input_tokens,
        output_tokens=result.total_output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        duration_s=result.duration_s,
        conversation_id=str(conversation_id),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    settings = get_settings()
    store = _get_store()

    if req.conversation_id:
        conversation_id = UUID(req.conversation_id)
        history_rows = await store.get_messages(conversation_id, limit=50)
        conversation_history = _rows_to_messages(history_rows)
    else:
        conversation_id = await store.create_conversation()
        conversation_history = []

    registry = ToolRegistry()
    register_builtin(registry)
    register_memory_tools(registry, store, conversation_id)

    planner = AnthropicTransport(model=settings.anthropic.planner_model)
    reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

    agent = AIAgent(
        transport=planner,
        tool_registry=registry,
        reflector_transport=reflector,
        memory_store=store,
        curator=_curator,
        compressor=_compressor,
        conversation_id=conversation_id,
        skill_manager=_get_skill_manager(),
    )

    async def _event_stream() -> AsyncGenerator[str, None]:
        import asyncio
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def enqueue(event: AgentEvent) -> None:
            await queue.put(event)

        async def run_agent() -> None:
            await agent.run(
                goal=req.message,
                on_event=enqueue,
                conversation_history=conversation_history,
            )
            await queue.put(None)

        task = asyncio.create_task(run_agent())

        # Emite conversation_id como primeiro evento
        yield f"data: {json.dumps({'type': 'conversation_id', 'data': {'id': str(conversation_id)}}, ensure_ascii=False)}\n\n"

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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rows_to_messages(rows: list[dict]) -> list[dict]:
    """Converte registros do banco para o formato de messages da API Anthropic."""
    messages = []
    for row in rows:
        role = row["role"]
        content = row["content"]
        if role in ("user", "assistant", "system"):
            tool_calls_raw = row.get("tool_calls")
            if role == "assistant" and tool_calls_raw:
                tool_calls = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                messages.append({"role": role, "content": content, "tool_calls": tool_calls})
            else:
                messages.append({"role": role, "content": content})
    return messages
