"""Parser e dispatcher de comandos de canal (F12).

Todos os canais (Discord, Slack, Email) usam os mesmos comandos.
O router chama dispatch_command() sem saber qual é o canal de origem.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from agent.channels.base import IncomingMessage
from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager

log = get_logger(__name__)

_HELP_TEXT = """Comandos disponíveis:
/help — esta ajuda
/status — status do agente
/mission <texto> — criar nova missão
/missions — listar missões ativas
/skills — listar skills disponíveis
/approve <id> — aprovar pendência (só em canais autorizados)
/deny <id> — negar pendência (só em canais autorizados)"""


async def dispatch_command(
    text: str,
    msg: IncomingMessage,
    session_id: str,
    orchestrator: Any | None,
    approval_manager: "ApprovalManager | None",
    approval_channels: set[str],
    db_pool: Any,
) -> str:
    """Despacha o comando e retorna o texto de resposta."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/help":
        return _HELP_TEXT

    if cmd == "/status":
        return await _cmd_status(orchestrator)

    if cmd in ("/mission",):
        return await _cmd_mission(arg, msg, session_id, orchestrator)

    if cmd == "/missions":
        return await _cmd_missions(orchestrator)

    if cmd == "/skills":
        return await _cmd_skills(orchestrator)

    if cmd in ("/approve", "/deny"):
        return await _cmd_approval(cmd, arg, msg, approval_manager, approval_channels)

    if cmd == "/cancel":
        return await _cmd_cancel(arg, orchestrator)

    return f"Comando desconhecido: {cmd}. Use /help para ver os comandos disponíveis."


async def _cmd_status(orchestrator: Any | None) -> str:
    if orchestrator is None:
        return "Agente: online (orquestrador indisponível)"
    return "Agente: online ✓"


async def _cmd_mission(
    text: str,
    msg: IncomingMessage,
    session_id: str,
    orchestrator: Any | None,
) -> str:
    if not text:
        return "Uso: /mission <objetivo da missão>"
    if orchestrator is None:
        return "Orquestrador indisponível."

    from agent.tasks.task import Task
    task = Task(
        content=text,
        source=f"channel:{msg.channel}",
        channel_ref={
            "session_id": session_id,
            "user_id": msg.user_id,
            "channel": msg.channel,
            "thread_id": msg.thread_id,
        },
        channel_target=msg.user_id,
    )
    result = await orchestrator.route(task)
    return result.final_text or "Missão iniciada."


async def _cmd_missions(orchestrator: Any | None) -> str:
    if orchestrator is None:
        return "Orquestrador indisponível."
    # Retorna texto estático se não houver API de listagem direta
    return "Use /status para ver o estado atual do agente."


async def _cmd_skills(orchestrator: Any | None) -> str:
    return "Skills: use a interface web em /api/v1/skills para listar."


async def _cmd_cancel(mission_id: str, orchestrator: Any | None) -> str:
    if not mission_id:
        return "Uso: /cancel <id da missão>"
    return f"Cancelamento de missão '{mission_id}' solicitado."


async def _cmd_approval(
    cmd: str,
    approval_id: str,
    msg: IncomingMessage,
    approval_manager: "ApprovalManager | None",
    approval_channels: set[str],
) -> str:
    """Processa /approve ou /deny. Gating por APPROVAL_CHANNELS."""
    if msg.channel not in approval_channels:
        log.info(
            "commands.approval_blocked",
            channel=msg.channel,
            approval_channels=list(approval_channels),
        )
        return (
            f"⛔ Canal '{msg.channel}' não está autorizado para aprovações. "
            f"Use um canal em APPROVAL_CHANNELS ({', '.join(sorted(approval_channels))})."
        )

    if not approval_id:
        return f"Uso: {cmd} <id da aprovação>"

    if approval_manager is None:
        return "Gerenciador de aprovações indisponível."

    decision = "approve" if cmd == "/approve" else "reject"
    try:
        from agent.approvals.manager import ApprovalNotFoundError, AlreadyDecidedError, ApprovalExpiredError
        await approval_manager.decide(
            approval_id=approval_id,
            decision=decision,
            decided_by=f"{msg.channel}:{msg.user_id}",
        )
        verb = "aprovada" if decision == "approve" else "negada"
        return f"✓ Aprovação {approval_id} {verb}."
    except Exception as exc:
        log.warning("commands.approval_error", approval_id=approval_id, error=str(exc))
        return f"Erro ao processar aprovação: {exc}"
