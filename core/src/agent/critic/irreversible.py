"""
Lista explícita de tools irreversíveis. Mantida à mão — não é heurística.

Para adicionar uma nova tool:
1. Adicione o nome aqui.
2. Se for uma skill, declare `irreversible: true` no manifesto da skill.

Sem os dois, o Critic não intercepta.
"""

IRREVERSIBLE_TOOLS: frozenset[str] = frozenset({
    "send_telegram",
    "send_email",
    "post_social_media",
    "git_push",
    "fs_delete",
    "execute_shell",
    "transfer_money",
    "delete_record",
    "execute_sql_write",
})


def is_irreversible(tool_name: str) -> bool:
    return tool_name in IRREVERSIBLE_TOOLS
