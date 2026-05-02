from pathlib import Path
from typing import Any

from agent.config import get_settings
from agent.observability.logger import get_logger
from agent.tools.base import BaseTool, ToolResult

log = get_logger(__name__)

_READ_LIMIT = 1 * 1024 * 1024   # 1 MB
_WRITE_LIMIT = 5 * 1024 * 1024  # 5 MB


def _resolve_and_check(path_str: str) -> tuple[Path, ToolResult | None]:
    """Resolve o path e valida contra a whitelist de workspace."""
    settings = get_settings()
    target = Path(path_str).resolve()
    allowed = [Path(p).resolve() for p in settings.agent.workspace_paths]

    for root in allowed:
        try:
            target.relative_to(root)
            return target, None
        except ValueError:
            continue

    return target, ToolResult(
        ok=False,
        error=f"path_outside_workspace: '{path_str}' não está em nenhum workspace permitido",
    )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Lê o conteúdo de um arquivo dentro do workspace permitido."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho absoluto do arquivo"},
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        target, err = _resolve_and_check(path_str)
        if err:
            return err

        if not target.exists():
            return ToolResult(ok=False, error=f"Arquivo não encontrado: {target}")
        if not target.is_file():
            return ToolResult(ok=False, error=f"Não é um arquivo: {target}")

        size = target.stat().st_size
        if size > _READ_LIMIT:
            return ToolResult(
                ok=False,
                error=f"file_too_large: arquivo tem {size} bytes (limite {_READ_LIMIT})",
            )

        content = target.read_text(errors="replace")
        log.info("tool.read_file", path=str(target), size=size)
        return ToolResult(ok=True, output=content)


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Escreve ou concatena conteúdo em um arquivo dentro do workspace."
    requires_confirmation = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho absoluto do arquivo"},
            "content": {"type": "string", "description": "Conteúdo a escrever"},
            "mode": {
                "type": "string",
                "enum": ["write", "append"],
                "default": "write",
                "description": "'write' substitui, 'append' concatena",
            },
        },
        "required": ["path", "content"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        content: str = kwargs["content"]
        mode: str = str(kwargs.get("mode", "write"))

        target, err = _resolve_and_check(path_str)
        if err:
            return err

        if len(content.encode()) > _WRITE_LIMIT:
            return ToolResult(
                ok=False,
                error=f"content_too_large: conteúdo excede {_WRITE_LIMIT} bytes",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        flag = "w" if mode == "write" else "a"
        target.open(flag).write(content)
        log.info("tool.write_file", path=str(target), mode=mode, bytes=len(content.encode()))
        return ToolResult(ok=True, output={"path": str(target), "mode": mode})


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "Lista arquivos e diretórios dentro do workspace."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho absoluto do diretório"},
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "Se true, lista recursivamente",
            },
        },
        "required": ["path"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        path_str: str = kwargs["path"]
        recursive: bool = bool(kwargs.get("recursive", False))

        target, err = _resolve_and_check(path_str)
        if err:
            return err

        if not target.exists():
            return ToolResult(ok=False, error=f"Diretório não encontrado: {target}")
        if not target.is_dir():
            return ToolResult(ok=False, error=f"Não é um diretório: {target}")

        glob = target.rglob("*") if recursive else target.iterdir()
        entries = []
        for p in sorted(glob):
            stat = p.stat()
            entries.append({
                "path": str(p),
                "type": "dir" if p.is_dir() else "file",
                "size": stat.st_size if p.is_file() else None,
            })

        log.info("tool.list_dir", path=str(target), entries=len(entries))
        return ToolResult(ok=True, output=entries)
