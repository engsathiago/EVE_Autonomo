from agent.observability.logger import get_logger
from agent.tools.base import BaseTool, ToolResult

log = get_logger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        log.debug("tool.registered", name=tool.name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def all_schemas(self) -> list[dict[str, object]]:
        return [t.to_anthropic_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    async def execute(self, name: str, args: dict[str, object]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            log.warning("tool.not_found", name=name)
            return ToolResult(ok=False, error=f"Tool '{name}' não encontrada")

        log.info("tool.execute", name=name, args=list(args))
        try:
            result = await tool.execute(**args)
        except Exception as exc:
            log.error("tool.execute.error", name=name, error=str(exc))
            return ToolResult(ok=False, error=str(exc))

        log.info("tool.execute.done", name=name, ok=result.ok)
        return result


def register_builtin(registry: ToolRegistry) -> None:
    from agent.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool
    from agent.tools.builtin.shell import ShellTool
    from agent.tools.builtin.web_search import WebSearchTool

    for tool in [ReadFileTool(), WriteFileTool(), ListDirTool(), ShellTool(), WebSearchTool()]:
        registry.register(tool)


def register_memory_tools(
    registry: ToolRegistry,
    store: "MemoryStore",  # type: ignore[name-defined]  # noqa: F821
    conversation_id: "UUID | None" = None,  # type: ignore[name-defined]  # noqa: F821
) -> None:

    from agent.tools.builtin.memory_tools import LerMemoriaTool, SalvarMemoriaTool

    registry.register(SalvarMemoriaTool(store=store, conversation_id=conversation_id))
    registry.register(LerMemoriaTool(store=store))
