"""
Agrega resultados de múltiplos subagentes (tier EPIC).

Se algum filho falhou, marca partial=True no resultado final.
O pai recebe um sumário e decide sobre retry.
"""

from __future__ import annotations

from agent.core import AgentResult
from agent.observability.logger import get_logger

log = get_logger(__name__)


def merge(results: list[AgentResult], parent_content: str = "") -> AgentResult:
    """
    Junta resultados de N subagentes em um AgentResult consolidado.

    - Se todos ok: final_text = concatenação dos textos com separadores
    - Se parcial: final_text inclui aviso de resultados faltando
    """
    successful = [
        r for r in results if not (r.approval_request and r.approval_request.get("error"))
    ]
    failed = [r for r in results if r.approval_request and r.approval_request.get("error")]
    partial = len(failed) > 0

    total_in = sum(r.total_input_tokens for r in results)
    total_out = sum(r.total_output_tokens for r in results)
    total_cost = sum(r.estimated_cost_usd for r in results)
    max_duration = max((r.duration_s for r in results), default=0.0)
    total_iterations = sum(r.iterations for r in results)

    parts: list[str] = []
    for i, r in enumerate(successful, start=1):
        if r.final_text:
            parts.append(f"[Subtask {i}]\n{r.final_text}")

    if partial:
        parts.append(
            f"\n[{len(failed)} subtask(s) failed: "
            + ", ".join(r.approval_request.get("error", "unknown") for r in failed)
            + "]"
        )
        log.warning("orchestrator.epic.partial", failed=len(failed), success=len(successful))

    final_text = "\n\n".join(parts) if parts else ""

    log.info(
        "orchestrator.epic.merged",
        total=len(results),
        success=len(successful),
        failed=len(failed),
        partial=partial,
    )

    return AgentResult(
        final_text=final_text,
        iterations=total_iterations,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        estimated_cost_usd=total_cost,
        duration_s=max_duration,
    )
