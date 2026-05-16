"""
Generates a human-readable Markdown benchmark report for each fine-tuning run.

Saved to models/checkpoints/<id>/benchmark_report.md.
Optionally sends a Telegram notification if telegram_chat_id is configured.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.observability.logger import get_logger

log = get_logger(__name__)


def generate_report(
    run_id: str,
    checkpoint_id: str | None,
    base_model: str,
    base_scores: dict[str, float],
    candidate_scores: dict[str, float],
    gate_decision: Any,  # GateDecision
    safety_result: Any,  # SafetyResult
    dataset_size: int,
    config: dict[str, Any],
    output_path: Path,
    triggered_by: str = "cli",
) -> str:
    """
    Generates the Markdown report and writes it to output_path.
    Returns the report as a string.
    """
    lines: list[str] = []
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    decision_emoji = "ACCEPTED" if gate_decision.accepted else "REJECTED"
    lines += [
        f"# Benchmark Report — {decision_emoji}",
        "",
        f"**Run ID:** `{run_id}`  ",
        f"**Checkpoint:** `{checkpoint_id or 'N/A'}`  ",
        f"**Base model:** `{base_model}`  ",
        f"**Gerado em:** {now_str}  ",
        f"**Disparado por:** {triggered_by}  ",
        f"**Dataset:** {dataset_size} exemplos  ",
        "",
    ]

    # Scores table
    lines += ["## Scores por eixo", "", "| Eixo | Base | Candidato | Delta | Status |",
               "|------|------|-----------|-------|--------|"]
    for axis_name, base_s in sorted(base_scores.items()):
        cand_s = candidate_scores.get(axis_name, 0.0)
        delta = (cand_s - base_s) * 100
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
        status = "✅" if delta >= 0 else "❌"
        lines.append(
            f"| {axis_name} | {base_s:.3f} | {cand_s:.3f} | {arrow} {abs(delta):.2f}% | {status} |"
        )

    # Overall delta
    details = gate_decision.details
    overall_delta = details.get("overall_delta_pct", 0.0)
    base_w = details.get("base_weighted", 0.0)
    cand_w = details.get("candidate_weighted", 0.0)
    lines += [
        "",
        f"**Score ponderado (base):** {base_w:.4f}  ",
        f"**Score ponderado (candidato):** {cand_w:.4f}  ",
        f"**Delta total:** {overall_delta:+.2f}%  ",
        "",
    ]

    # Gate decision
    lines += ["## Decisão do Gate", ""]
    if gate_decision.accepted:
        lines.append("**✅ APROVADO** — checkpoint marcado como `candidate`.")
    else:
        lines.append(f"**❌ REJEITADO** — razão: `{gate_decision.reason}`")
    lines.append("")

    # Safety
    lines += ["## Safety Check", ""]
    safety_status = "✅ Passou" if safety_result.passed else "❌ Falhou"
    lines.append(f"**Resultado:** {safety_status}  ")
    lines.append(f"**Tasks avaliadas:** {safety_result.total_tasks}  ")
    lines.append(f"**Recusas do base:** {safety_result.base_refusals}  ")
    lines.append(f"**Recusas do candidato:** {safety_result.candidate_refusals}  ")
    if safety_result.regressions:
        lines += ["", "### Regressões de segurança", ""]
        for reg in safety_result.regressions:
            lines.append(f"- Task `{reg['task_id']}`: candidato aceitou onde base recusou")
            lines.append(f"  - Prompt: _{reg['prompt_preview']}_")
    lines.append("")

    # Hyperparameters
    lines += ["## Hiperparâmetros", "", "```yaml"]
    for k, v in sorted(config.items()):
        lines.append(f"{k}: {v}")
    lines += ["```", ""]

    report = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    log.info("reports.written", path=str(output_path))
    return report


async def notify_telegram(
    report_summary: str,
    run_id: str,
    decision: str,
    telegram_chat_id: str | None,
    telegram_token: str | None,
) -> None:
    """
    Sends a Telegram notification with the run summary.
    Logs and continues if telegram_chat_id is absent — never raises.
    """
    if not telegram_chat_id or not telegram_token:
        log.info("reports.telegram_skip", reason="telegram_chat_id ou token ausente")
        return

    text = (
        f"🤖 *F13 fine-tuning run concluído*\n\n"
        f"Run: `{run_id}`\n"
        f"Decisão: *{decision}*\n\n"
        f"{report_summary[:500]}"
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                json={
                    "chat_id": telegram_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
        log.info("reports.telegram_sent", chat_id=telegram_chat_id)
    except Exception as exc:
        log.info("reports.telegram_error", error=str(exc))
