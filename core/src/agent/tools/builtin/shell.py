import asyncio
import re
import time
from typing import Any

from agent.config import get_settings
from agent.observability.logger import get_logger
from agent.tools.base import BaseTool, ToolResult

log = get_logger(__name__)

_MAX_TIMEOUT = 300
_OUTPUT_LIMIT = 100 * 1024  # 100 KB por stream


def _check_blacklist(command: str) -> str | None:
    """Retorna o padrão que bloqueou, ou None se aprovado."""
    blacklist = get_settings().agent.shell_blacklist
    for pattern in blacklist:
        if re.search(pattern, command):
            return pattern
    return None


class ShellTool(BaseTool):
    name = "shell"
    description = (
        "Executa um comando shell. Use com cuidado — comandos destrutivos "
        "são bloqueados por blacklist."
    )
    requires_confirmation = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando shell a executar"},
            "timeout": {
                "type": "integer",
                "default": 30,
                "description": f"Timeout em segundos (máx {_MAX_TIMEOUT})",
            },
        },
        "required": ["command"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs["command"]
        timeout: int = min(int(kwargs.get("timeout", 30)), _MAX_TIMEOUT)

        blocked = _check_blacklist(command)
        if blocked:
            log.warning("tool.shell.blocked", command=command, pattern=blocked)
            return ToolResult(
                ok=False,
                error=f"Comando bloqueado por segurança (padrão: {blocked!r})",
            )

        log.info("tool.shell.execute", command=command, timeout=timeout)
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ToolResult(
                ok=False,
                error=f"Timeout após {timeout}s",
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        def _decode(b: bytes) -> str:
            text = b.decode(errors="replace")
            if len(text) > _OUTPUT_LIMIT:
                text = text[:_OUTPUT_LIMIT] + f"\n[... truncado após {_OUTPUT_LIMIT} bytes]"
            return text

        stdout = _decode(stdout_bytes)
        stderr = _decode(stderr_bytes)
        returncode = proc.returncode or 0

        log.info(
            "tool.shell.done",
            returncode=returncode,
            duration_ms=duration_ms,
            stdout_len=len(stdout),
            stderr_len=len(stderr),
        )

        return ToolResult(
            ok=returncode == 0,
            output={
                "stdout": stdout,
                "stderr": stderr,
                "returncode": returncode,
                "duration_ms": duration_ms,
            },
            error=stderr if returncode != 0 else None,
        )
