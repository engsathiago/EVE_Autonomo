from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from agent.channels.base import Channel
from agent.observability.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["channels"])


class MessageRequest(BaseModel):
    session_id: str
    text: str
    channel: Channel
    user_id: str
    metadata: dict[str, Any] = {}


class MessageResponse(BaseModel):
    type: str  # "reply" | "approval_request"
    text: str | None = None
    approval_id: str | None = None
    skill_name: str | None = None
    summary: str | None = None
    expires_at: str | None = None
    conversation_id: str | None = None


def make_messages_router(get_agent_deps: Any) -> APIRouter:
    """
    Factory que cria o router injetando as dependências de agent (store, skill_manager, etc.)
    via callable `get_agent_deps()` que retorna um dict com as instâncias.
    """

    @router.post("/messages", response_model=MessageResponse)
    async def receive_message(req: MessageRequest) -> MessageResponse:
        deps = get_agent_deps()
        store = deps["memory_store"]
        skill_manager = deps["skill_manager"]
        model_router = deps["model_router"]
        curator = deps["curator"]
        compressor = deps["compressor"]
        settings = deps["settings"]

        from agent.core import AIAgent
        from agent.tools.registry import ToolRegistry, register_builtin, register_memory_tools
        from agent.transports import AnthropicTransport

        # session_id "tg:<chat_id>" → conversa isolada por usuário
        # Usamos o session_id como conversation_id string (lookup ou cria)
        conversation_id = await _resolve_conversation(store, req.session_id)

        history_rows = await store.get_messages(conversation_id, limit=50)
        history = _rows_to_messages(history_rows)

        registry = ToolRegistry()
        register_builtin(registry)
        register_memory_tools(registry, store, conversation_id)

        planner = AnthropicTransport(model=settings.anthropic.planner_model)
        reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

        # Thread channel context so SkillManager can pass to ApprovalManager
        if skill_manager is not None:
            skill_manager._channel = req.channel.value
            skill_manager._channel_ref = {
                "user_id": req.user_id,
                **req.metadata,
            }

        agent = AIAgent(
            transport=planner,
            tool_registry=registry,
            reflector_transport=reflector,
            memory_store=store,
            curator=curator,
            compressor=compressor,
            conversation_id=conversation_id,
            skill_manager=skill_manager,
            model_router=model_router,
        )

        result = await agent.run(goal=req.text, conversation_history=history)

        if result.approval_request:
            ar = result.approval_request
            return MessageResponse(
                type="approval_request",
                approval_id=ar.get("approval_id"),
                skill_name=ar.get("skill_name"),
                summary=ar.get("summary"),
                expires_at=str(ar.get("expires_at")) if ar.get("expires_at") else None,
                conversation_id=result.conversation_id,
            )

        return MessageResponse(
            type="reply",
            text=result.final_text,
            conversation_id=result.conversation_id,
        )

    return router


async def _resolve_conversation(store: Any, session_id: str) -> UUID:
    """Get-or-create de conversa pelo session_id estável do canal."""
    existing = await store.get_conversation_by_session_id(session_id)
    if existing:
        return existing
    return await store.create_conversation(session_id=session_id)


def _rows_to_messages(rows: list[dict]) -> list[dict]:
    import json

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
