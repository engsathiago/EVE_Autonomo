"""
Classificação args-aware de tool calls irreversíveis.

Diferença do irreversible.py (frozenset por nome):
- Aceita args e retorna motivo detalhado
- write_file em /tmp ou sandbox/ é considerado reversível
- shell só é irreversível se o comando contém padrões destrutivos
- Fail-safe: tools desconhecidas são tratadas como irreversíveis

Usado por AIAgent._maybe_gate_tool; irreversible.py continua sendo usado
pelo Critic.needs_critic() para compatibilidade com o loop autônomo.
"""

from __future__ import annotations

import re
from typing import Any

IRREVERSIBLE_SHELL_PATTERNS: list[str] = [
    r"\brm\b",
    r"\bmv\b",
    r"\bgit\s+push\b",
    r"\bdocker\b",
    r"\bsudo\b",
    r"curl\s+-X\s+(POST|DELETE|PUT)",
    r">\s*\S+",
]

_SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "list_dir",
        "web_search",
        "web_fetch",
        "ler_memoria",
        "salvar_memoria",
        "delegate",
    }
)

_ALWAYS_IRREVERSIBLE_TOOLS: frozenset[str] = frozenset(
    {
        "send_telegram",
        "send_email",
        "send_slack",
        "send_discord",
        "post_social_media",
        "transfer_money",
        "fs_delete",
        "execute_shell",
        "git_push",
        "delete_record",
        "execute_sql_write",
        "exec_sandbox",
    }
)


def is_irreversible(tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
    """
    Classifica se (tool_name, args) representa uma ação irreversível.

    Returns:
        (is_irreversible, reason_str)
        reason_str é vazia quando is_irreversible=False.
    """
    if tool_name in _SAFE_TOOLS:
        return False, ""

    if tool_name in _ALWAYS_IRREVERSIBLE_TOOLS:
        return True, f"envio/operação externa via {tool_name}"

    if tool_name == "write_file":
        path = str(args.get("path", ""))
        if path.startswith("/tmp") or "sandbox/" in path:
            return False, ""
        return True, f"write_file fora de sandbox: {path!r}"

    if tool_name == "shell":
        cmd = str(args.get("command", ""))
        for pat in IRREVERSIBLE_SHELL_PATTERNS:
            if re.search(pat, cmd):
                return True, f"shell com padrão destrutivo {pat!r}: {cmd[:80]}"
        return False, ""

    return True, f"tool desconhecida (fail-safe): {tool_name}"
