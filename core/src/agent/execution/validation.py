"""
Helper central para validar se uma execução de AgentResult realmente invocou tools
ou apenas gerou prosa. Usado por mission executor, subagent runner e qualquer outro
site que precise distinguir "executou" de "respondeu".

Função pura — sem efeitos colaterais, sem I/O, fácil de testar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core import AgentResult


class ExecutionVerdict(Enum):
    EXECUTED = "executed"
    # Houve >=1 tool call registrada no AgentResult.tool_calls_made

    PROSE_ONLY = "prose_only"
    # LLM respondeu só texto — zero tool calls, sem exception, sem planejamento declarado

    EXCEPTION = "exception"
    # Erro durante a execução capturado em AgentResult.exception

    INTENT_PLANNING = "intent_planning"
    # Subagente declarou explicitamente intent="planning" (sem tool call esperado)
    # Só válido quando allow_planning=True E result.intent == "planning"


@dataclass(frozen=True)
class ExecutionAnalysis:
    verdict: ExecutionVerdict
    tools_invoked: list[str]       # nomes das tools REALMENTE chamadas (de tool_calls_made)
    tool_call_count: int           # len(tools_invoked)
    has_structured_output: bool    # alguma call retornou output com campos além de "text"?
    reason: str                    # explicação humana


def analyze_turn(result: "AgentResult", *, allow_planning: bool = False) -> ExecutionAnalysis:
    """
    Analisa o resultado de um AgentResult e retorna um ExecutionAnalysis com verdict.

    Regras (em ordem de prioridade):
    1. Se result.exception não for None → EXCEPTION
    2. Se há tool calls em result.tool_calls_made → EXECUTED
    3. Se allow_planning=True E result.intent == "planning" → INTENT_PLANNING
    4. Caso contrário → PROSE_ONLY

    Nota: allow_planning=True sozinho não é suficiente para INTENT_PLANNING.
    O AgentResult precisa ter intent="planning" declarado explicitamente.
    Caso contrário, prosa sem tool call ainda é PROSE_ONLY — não escapa por flag.
    """
    tool_calls = result.tool_calls_made
    tools_invoked = [tc.tool_name for tc in tool_calls]
    tool_call_count = len(tool_calls)
    has_structured = any(tc.has_structured_output for tc in tool_calls)

    # 1. Exception tem prioridade máxima
    if result.exception is not None:
        return ExecutionAnalysis(
            verdict=ExecutionVerdict.EXCEPTION,
            tools_invoked=tools_invoked,
            tool_call_count=tool_call_count,
            has_structured_output=has_structured,
            reason=f"Execução encerrou com exception: {result.exception[:200]}",
        )

    # 2. Houve tool calls — execução real
    if tool_call_count > 0:
        return ExecutionAnalysis(
            verdict=ExecutionVerdict.EXECUTED,
            tools_invoked=tools_invoked,
            tool_call_count=tool_call_count,
            has_structured_output=has_structured,
            reason=f"{tool_call_count} tool(s) invocada(s): {', '.join(tools_invoked)}",
        )

    # 3. Planejamento declarado explicitamente (e flag habilitada)
    if allow_planning and result.intent == "planning":
        return ExecutionAnalysis(
            verdict=ExecutionVerdict.INTENT_PLANNING,
            tools_invoked=[],
            tool_call_count=0,
            has_structured_output=False,
            reason="Turn de planejamento explícito — intent='planning' declarado pelo agente",
        )

    # 4. Prosa pura — nenhum dos casos acima
    snippet = (result.final_text or "")[:120].replace("\n", " ")
    return ExecutionAnalysis(
        verdict=ExecutionVerdict.PROSE_ONLY,
        tools_invoked=[],
        tool_call_count=0,
        has_structured_output=False,
        reason=f"Nenhuma tool chamada; resposta textual: '{snippet}'",
    )
