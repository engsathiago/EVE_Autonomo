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
    # Política de sandbox para execuções deste subagente (Fase 8)
    # "untrusted" → require_critic_approval=True (skills auto-geradas na F9)
    sandbox_policy: str = "default"
    # D.1: tools DECLARADAS pelo step de missão (source=declared).
    # Usado pelo pool para validação: se não-vazio, todas as tools listadas
    # devem existir no registry builtin, senão o subagente é rejeitado com
    # MissingRequiredTool antes de executar.
    # Para tools inferidas (keyword/LLM/fallback), este campo fica vazio.
    tools_required: list[str] = field(default_factory=list)

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
