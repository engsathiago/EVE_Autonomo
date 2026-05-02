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
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
