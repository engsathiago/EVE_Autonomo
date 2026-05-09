from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SubAgentContext:
    """Tudo que o filho pode ver — nada além disso chega até ele."""

    task: str
    tools_allowed: list[str]
    extra_context: str | None = None
    return_format: Literal["text", "json", "json_list"] = "text"
    timeout_s: int = 120
    max_iterations: int = 6
    # Referência do canal pai (para propagar approvals)
    channel_ref: dict = field(default_factory=dict)
    parent_task_id: str | None = None

    def build_system_prompt(self) -> str:
        parts = [
            "You are a focused subagent. Solve exactly the task given to you.",
            f"Use ONLY these tools: {', '.join(self.tools_allowed) or 'none'}.",
            f"Return your answer in format: {self.return_format}.",
            "Do NOT expand scope. When done, stop immediately.",
        ]
        if self.extra_context:
            parts.append(f"\nAdditional context:\n{self.extra_context}")
        return "\n".join(parts)

    def build_user_message(self) -> str:
        if self.return_format == "json":
            return f"{self.task}\n\nRespond with a single JSON object."
        if self.return_format == "json_list":
            return f"{self.task}\n\nRespond with a JSON array."
        return self.task
