from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_MODEL_RE = re.compile(
    r"^(anthropic|openai|openrouter|ollama):[\w./\-]+(:[\w.\-]+)?$"
)

ArgumentType = Literal["string", "integer", "float", "boolean", "enum", "datetime"]


class SkillArgument(BaseModel):
    name: str
    type: ArgumentType = "string"
    required: bool = False
    default: Any = None
    values: list[str] | None = None  # para type=enum
    description: str | None = None


class SkillManifest(BaseModel):
    name: str
    version: int = 1
    description: str
    arguments: list[SkillArgument] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    model: str | None = None   # ex: 'ollama:qwen2.5:7b' — None herda DEFAULT_MODEL
    # Preenchido pelo loader — não vem do frontmatter
    prompt: str = ""
    source_path: str = ""
    content_hash: str = ""

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str | None) -> str | None:
        if v is not None and not _MODEL_RE.match(v):
            raise ValueError(
                f"Campo 'model' inválido: {v!r}. "
                "Formato: 'provider:model_id' — ex: 'ollama:qwen2.5:7b', 'anthropic:claude-haiku-4-5'"
            )
        return v


class SkillMatch(BaseModel):
    manifest: SkillManifest
    score: float  # 0.0–1.0; 1.0 = match exato por nome


class SkillResult(BaseModel):
    skill_name: str
    skill_version: int
    output: Any
    success: bool
    error: str | None = None
    latency_ms: int = 0


class SkillInvocationRecord(BaseModel):
    """Registro para persistir em skill_invocations."""
    session_id: UUID
    skill_name: str
    skill_version: int
    arguments: dict[str, Any]
    result: Any | None = None
    success: bool = False
    error: str | None = None
    latency_ms: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SkillRequiresApproval(Exception):
    def __init__(self, skill_name: str) -> None:
        super().__init__(
            f"Skill '{skill_name}' requires_approval=true. "
            "Approve via CLI: agent skill approve <name>"
        )
        self.skill_name = skill_name


class SkillNotFound(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Skill not found: '{name}'")
        self.skill_name = name


class SkillError(Exception):
    pass
