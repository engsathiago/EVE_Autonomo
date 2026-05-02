import pytest

from agent.tools.base import BaseTool, ToolResult
from agent.tools.registry import ToolRegistry


class EchoTool(BaseTool):
    name = "echo"
    description = "Ecoa o input"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(ok=True, output=kwargs.get("text"))


class BrokenTool(BaseTool):
    name = "broken"
    description = "Sempre falha"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: object) -> ToolResult:
        raise RuntimeError("falha intencional")


def test_register_and_get(registry: ToolRegistry) -> None:
    registry.register(EchoTool())
    assert registry.get("echo") is not None


def test_get_unknown_returns_none(registry: ToolRegistry) -> None:
    assert registry.get("fantasma") is None


def test_names(registry: ToolRegistry) -> None:
    registry.register(EchoTool())
    assert "echo" in registry.names()


def test_all_schemas(registry: ToolRegistry) -> None:
    registry.register(EchoTool())
    schemas = registry.all_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"


@pytest.mark.asyncio
async def test_execute_success(registry: ToolRegistry) -> None:
    registry.register(EchoTool())
    result = await registry.execute("echo", {"text": "hello"})
    assert result.ok is True
    assert result.output == "hello"


@pytest.mark.asyncio
async def test_execute_unknown_tool(registry: ToolRegistry) -> None:
    result = await registry.execute("fantasma", {})
    assert result.ok is False
    assert "não encontrada" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_encapsulates_errors(registry: ToolRegistry) -> None:
    registry.register(BrokenTool())
    result = await registry.execute("broken", {})
    assert result.ok is False
    assert "falha intencional" in (result.error or "")
