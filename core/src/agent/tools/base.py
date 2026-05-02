from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    ok: bool
    output: Any = None
    error: str | None = None


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_confirmation: bool = False

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
