"""
Tool `delegate` que o AIAgent pai usa para criar subagentes.

O Orchestrator detecta chamadas a esta tool e as intercepta antes de
executar via ToolRegistry — cria o SubagentPool.spawn() em vez de
executar um handler local.

Se o pai usar sem Orchestrator (ex: testes), a tool executa via pool
passado na inicialização.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from agent.subagents.pool import SubagentPool
    from agent.tasks.task import Task


DELEGATE_SCHEMA = {
    "name": "delegate",
    "description": (
        "Delega uma sub-tarefa a um subagente isolado. "
        "Use quando a tarefa tem escopo restrito ou pode ser paralelizada. "
        "O subagente não vê o contexto desta conversa — apenas o que você passar em 'task'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Descrição precisa da sub-tarefa a executar.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de tools que o subagente pode usar.",
                "default": [],
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout em segundos (default: 120).",
                "default": 120,
            },
            "return_format": {
                "type": "string",
                "enum": ["text", "json", "json_list"],
                "description": "Formato da resposta esperada.",
                "default": "text",
            },
            "extra_context": {
                "type": "string",
                "description": "Contexto adicional para o subagente (opcional).",
            },
        },
        "required": ["task"],
    },
}


class DelegateTool(BaseTool):
    """Tool registrável que o pai usa para delegar subtarefas."""

    name = "delegate"
    description = DELEGATE_SCHEMA["description"]
    input_schema: dict[str, Any] = DELEGATE_SCHEMA["input_schema"]
    requires_confirmation = False

    def __init__(self, pool: "SubagentPool", parent_task: "Task") -> None:
        self._pool = pool
        self._parent_task = parent_task

    async def execute(self, **kwargs: Any) -> ToolResult:
        from agent.subagents.context import SubAgentContext

        ctx = SubAgentContext(
            task=kwargs["task"],
            tools_allowed=kwargs.get("tools", []),
            extra_context=kwargs.get("extra_context"),
            return_format=kwargs.get("return_format", "text"),
            timeout_s=int(kwargs.get("timeout", 120)),
            channel_ref=self._parent_task.channel_ref,
            parent_task_id=str(self._parent_task.id),
        )

        result = await self._pool.spawn(ctx, self._parent_task)

        if result.approval_request and result.approval_request.get("error"):
            return ToolResult(
                ok=False,
                error=f"subagent error: {result.approval_request['error']}",
            )

        return ToolResult(
            ok=True,
            output={
                "result": result.final_text,
                "iterations": result.iterations,
                "tokens_used": result.total_input_tokens + result.total_output_tokens,
                "cost_usd": result.estimated_cost_usd,
            },
        )
