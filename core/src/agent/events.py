import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    type: Literal[
        "iteration_start",
        "planner_text",
        "tool_call",
        "tool_result",
        "reflection",
        "done",
        "error",
        # Fase 8: sandbox
        "sandbox.execution.started",
        "sandbox.execution.finished",
        "sandbox.network.denied",
        "sandbox.limit.exceeded",
        # Fase 9: skills auto-geradas
        "skill.candidate_detected",
        "skill.synthesized",
        "skill.validation_passed",
        "skill.validation_failed",
        "skill.promoted",
        "skill.rejected",
        "skill.executed",
        "skill.fallback_to_exec",
        "skill.deprecated",
        "skill.flagged",
        "skill.matured",
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


# Registry de handlers para eventos sandbox.* (sem handler = silencioso)
_sandbox_handlers: list[Any] = []

# Registry de handlers para eventos skill.*
_skill_handlers: list[Any] = []


def register_sandbox_handler(handler: Any) -> None:
    """Registra um coroutine handler(event_type, data) para eventos sandbox.*"""
    _sandbox_handlers.append(handler)


def register_skill_handler(handler: Any) -> None:
    """Registra um coroutine handler(event_type, data) para eventos skill.*"""
    _skill_handlers.append(handler)


async def emit_sandbox_event(event_type: str, data: dict[str, Any]) -> None:
    """Emite evento sandbox para todos os handlers registrados."""
    import asyncio
    for handler in _sandbox_handlers:
        try:
            result = handler(event_type, data)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass


async def emit_skill_event(event_type: str, data: dict[str, Any]) -> None:
    """Emite evento skill.* para todos os handlers registrados."""
    import asyncio
    for handler in _skill_handlers:
        try:
            result = handler(event_type, data)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass
