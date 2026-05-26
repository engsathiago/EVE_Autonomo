"""
Testes para agent.execution.validation.analyze_turn().

Garante que o helper distingue corretamente execução real de prosa.
Todos os testes são síncronos e não fazem I/O — função pura.

Se qualquer teste aqui falhar, o fix do executor está quebrado.
"""

import pytest

from agent.core import AgentResult, ToolCallSummary
from agent.execution.validation import ExecutionVerdict, analyze_turn


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _base_result(**kwargs) -> AgentResult:
    """Constrói um AgentResult com defaults razoáveis."""
    defaults = dict(
        final_text="",
        iterations=1,
        total_input_tokens=100,
        total_output_tokens=50,
        estimated_cost_usd=0.001,
        duration_s=0.5,
    )
    defaults.update(kwargs)
    return AgentResult(**defaults)


def _make_call(name: str, *, succeeded: bool = True, structured: bool = False) -> ToolCallSummary:
    return ToolCallSummary(
        tool_name=name,
        succeeded=succeeded,
        has_structured_output=structured,
        duration_ms=10,
    )


# ─── Caso 1: Tool call único, sucesso → EXECUTED ────────────────────────────


def test_single_tool_call_executed():
    result = _base_result(
        tool_calls_made=[_make_call("read_file", succeeded=True)],
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXECUTED
    assert analysis.tool_call_count == 1
    assert "read_file" in analysis.tools_invoked


# ─── Caso 2: Múltiplas tool calls → EXECUTED, tool_call_count == N ──────────


def test_multiple_tool_calls_executed():
    result = _base_result(
        tool_calls_made=[
            _make_call("list_dir"),
            _make_call("read_file"),
            _make_call("write_file"),
        ],
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXECUTED
    assert analysis.tool_call_count == 3
    assert analysis.tools_invoked == ["list_dir", "read_file", "write_file"]


# ─── Caso 3: Zero tool calls, texto presente → PROSE_ONLY ───────────────────


def test_zero_tool_calls_prose_only():
    result = _base_result(
        final_text="Não tenho acesso ao sistema de arquivos do seu ambiente local.",
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.PROSE_ONLY
    assert analysis.tool_call_count == 0
    assert analysis.tools_invoked == []


# ─── Caso 4: Zero tool calls, allow_planning=False → PROSE_ONLY ─────────────


def test_zero_tool_calls_allow_planning_false_is_prose():
    """
    allow_planning=False não muda nada: prosa sem tool call continua sendo PROSE_ONLY.
    """
    result = _base_result(
        final_text="Vou analisar o problema e propor um plano.",
    )
    analysis = analyze_turn(result, allow_planning=False)
    assert analysis.verdict == ExecutionVerdict.PROSE_ONLY


# ─── Caso 5: allow_planning=True + intent="planning" → INTENT_PLANNING ─────


def test_planning_intent_explicit():
    """
    Com allow_planning=True E intent="planning" declarado, sem tool calls
    é legítimo — subagente de planejamento puro.
    """
    result = _base_result(
        final_text="Decomposição da tarefa em 3 subtasks: ...",
        intent="planning",
    )
    analysis = analyze_turn(result, allow_planning=True)
    assert analysis.verdict == ExecutionVerdict.INTENT_PLANNING
    assert analysis.tool_call_count == 0


# ─── Caso 6: allow_planning=True SEM intent declarado → PROSE_ONLY ──────────


def test_planning_flag_without_intent_is_prose():
    """
    Só o flag allow_planning=True não basta — sem intent="planning" no AgentResult,
    a ausência de tool calls ainda é PROSE_ONLY.
    """
    result = _base_result(
        final_text="Entendi a tarefa. Vou organizar os passos.",
        intent=None,  # explícito: sem declaração de planejamento
    )
    analysis = analyze_turn(result, allow_planning=True)
    assert analysis.verdict == ExecutionVerdict.PROSE_ONLY


# ─── Caso 7: Exception durante execução → EXCEPTION ────────────────────────


def test_exception_verdict():
    result = _base_result(
        exception="ConnectionError: timeout ao chamar API",
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXCEPTION
    assert "ConnectionError" in analysis.reason


# ─── Caso 8: Tool call retorna {"text": "..."} → EXECUTED, has_structured=False


def test_tool_call_text_only_output_not_structured():
    """
    Uma tool call que retorna {"text": "prosa"} é EXECUTED (chamou a tool),
    mas has_structured_output=False (output não tem campos além de "text").
    """
    result = _base_result(
        tool_calls_made=[
            _make_call("summarize_text", succeeded=True, structured=False),
        ],
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXECUTED
    assert analysis.has_structured_output is False


# ─── Caso 9: Tool com output estruturado → has_structured_output=True ───────


def test_tool_call_structured_output():
    """
    Tool que retorna {"files": [...], "count": 5} → has_structured_output=True.
    """
    result = _base_result(
        tool_calls_made=[
            _make_call("list_dir", succeeded=True, structured=True),
        ],
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXECUTED
    assert analysis.has_structured_output is True


# ─── Caso 10: Exception tem prioridade sobre tool calls ─────────────────────


def test_exception_priority_over_tool_calls():
    """
    Se há exception E tool calls, exception vence (prioridade máxima).
    """
    result = _base_result(
        tool_calls_made=[_make_call("read_file")],
        exception="RuntimeError inesperado",
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXCEPTION


# ─── Caso 11: Tool com falha ainda conta como EXECUTED ──────────────────────


def test_failed_tool_call_still_counts_as_executed():
    """
    Uma tool call que falhou (succeeded=False) ainda prova que o LLM chamou a tool.
    A falha é informativa, mas não muda o verdict para PROSE_ONLY.
    """
    result = _base_result(
        tool_calls_made=[
            _make_call("execute_shell", succeeded=False),
        ],
    )
    analysis = analyze_turn(result)
    assert analysis.verdict == ExecutionVerdict.EXECUTED
    assert analysis.tool_call_count == 1
