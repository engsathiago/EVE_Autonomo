"""ChannelRouter — único ponto de entrada para mensagens externas (F12).

Responsabilidades:
1. Receber IncomingMessage de qualquer adapter.
2. Verificar allowlist (delega ao adapter.is_authorized).
3. Aplicar rate limit por (canal, user_id) e por canal.
4. Persistir direction=in antes de processar.
5. Detectar comando vs chat livre, despachar para orchestrator ou approval_manager.
6. Enviar resposta via adapter.send().
7. Persistir direction=out após enviar.

Roteamento é 100% responsabilidade do router + adapter. O orchestrator
recebe apenas Task com channel_ref para correlação — sem ramificação por canal.
"""
from __future__ import annotations

import collections
import os
import time
from typing import TYPE_CHECKING, Any

from agent.channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage
from agent.channels import metrics as ch_metrics
from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager

log = get_logger(__name__)

_APPROVAL_CHANNELS_DEFAULT = ["telegram", "web"]

# ── Rate limiter simples (sliding window in-memory) ──────────────────────────

class _SlidingWindow:
    """Contador de hits numa janela deslizante de 60 segundos."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._hits: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        dq = self._hits[key]
        cutoff = now - 60.0
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self._limit:
            return False
        dq.append(now)
        return True


# ── ChannelRouter ────────────────────────────────────────────────────────────

class ChannelRouter:
    def __init__(
        self,
        adapters: list[ChannelAdapter],
        orchestrator: Any | None,
        approval_manager: "ApprovalManager | None",
        db_pool: Any,
        rate_limit_user_per_min: int = 20,
        rate_limit_channel_per_min: int = 120,
        approval_channels: list[str] | None = None,
    ) -> None:
        self._adapters: dict[str, ChannelAdapter] = {a.name: a for a in adapters}
        self._orchestrator = orchestrator
        self._approval_manager = approval_manager
        self._db_pool = db_pool
        self._user_rl = _SlidingWindow(rate_limit_user_per_min)
        self._channel_rl = _SlidingWindow(rate_limit_channel_per_min)
        self._approval_channels = set(
            approval_channels if approval_channels is not None
            else _parse_approval_channels()
        )

    async def handle(self, msg: IncomingMessage) -> None:
        """Processa uma IncomingMessage de ponta a ponta."""
        adapter = self._adapters.get(msg.channel)
        if adapter is None:
            log.warning("router.unknown_channel", channel=msg.channel)
            return

        # 1. Allowlist
        if not await adapter.is_authorized(msg.user_id):
            log.info(
                "router.unauthorized",
                channel=msg.channel,
                user_id=msg.user_id,
            )
            ch_metrics.unauthorized_total.labels(channel=msg.channel).inc()
            return

        # 2. Rate limit por usuário
        user_key = f"{msg.channel}:{msg.user_id}"
        if not self._user_rl.allow(user_key):
            log.info("router.rate_limited", channel=msg.channel, user_id=msg.user_id, reason="user")
            ch_metrics.rate_limited_total.labels(channel=msg.channel, reason="user").inc()
            await adapter.send(msg.user_id, OutgoingMessage(
                text="⚠️ Muitas mensagens. Aguarde um momento.",
                thread_id=msg.thread_id,
            ))
            return

        # 3. Rate limit por canal
        if not self._channel_rl.allow(msg.channel):
            log.info("router.rate_limited", channel=msg.channel, user_id=msg.user_id, reason="channel")
            ch_metrics.rate_limited_total.labels(channel=msg.channel, reason="channel").inc()
            return

        session_id = f"{msg.channel}:{msg.user_id}"

        # 4. Persistir direction=in
        await self._persist(msg.channel, "in", msg.user_id, msg.user_display, msg.text, msg.thread_id, None, session_id)
        ch_metrics.messages_total.labels(channel=msg.channel, direction="in").inc()

        # 5. Despachar
        t0 = time.monotonic()
        response_text = await self._dispatch(msg, session_id, adapter)
        latency = time.monotonic() - t0
        ch_metrics.message_latency_seconds.labels(channel=msg.channel, direction="out").observe(latency)

        if response_text is None:
            return

        # 6. Enviar resposta
        out_msg = OutgoingMessage(text=response_text, thread_id=msg.thread_id)
        await adapter.send(msg.user_id, out_msg)

        # 7. Persistir direction=out
        await self._persist(msg.channel, "out", msg.user_id, None, response_text, msg.thread_id, None, session_id)
        ch_metrics.messages_total.labels(channel=msg.channel, direction="out").inc()

    async def _dispatch(
        self,
        msg: IncomingMessage,
        session_id: str,
        adapter: ChannelAdapter,
    ) -> str | None:
        """Decide o que fazer com a mensagem e retorna o texto de resposta (ou None)."""
        text = msg.text.strip()

        # Comando slash
        if text.startswith("/"):
            return await self._handle_command(text, msg, session_id)

        # Chat livre → orchestrator
        return await self._route_to_orchestrator(msg, session_id)

    async def _handle_command(
        self,
        text: str,
        msg: IncomingMessage,
        session_id: str,
    ) -> str | None:
        """Processa comandos /xxx. Retorna texto de resposta."""
        from agent.channels.commands import dispatch_command
        return await dispatch_command(
            text=text,
            msg=msg,
            session_id=session_id,
            orchestrator=self._orchestrator,
            approval_manager=self._approval_manager,
            approval_channels=self._approval_channels,
            db_pool=self._db_pool,
        )

    async def _route_to_orchestrator(
        self,
        msg: IncomingMessage,
        session_id: str,
    ) -> str:
        """Encaminha chat livre ao orchestrator. Retorna texto final."""
        if self._orchestrator is None:
            log.warning("router.orchestrator_unavailable", channel=msg.channel)
            return "Agente temporariamente indisponível."

        from agent.tasks.task import Task
        task = Task(
            content=msg.text,
            source=f"channel:{msg.channel}",
            channel_ref={
                "session_id": session_id,
                "user_id": msg.user_id,
                "channel": msg.channel,
                "thread_id": msg.thread_id,
            },
            channel_target=msg.user_id,
        )

        ch_metrics.missions_dispatched_total.labels(channel=msg.channel).inc()

        result = await self._orchestrator.route(task)
        return result.final_text if result.final_text else "✓"

    async def _persist(
        self,
        channel: str,
        direction: str,
        user_id: str,
        user_display: str | None,
        text: str,
        thread_id: str | None,
        mission_id: str | None,
        session_id: str,
    ) -> None:
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO channel_messages
                        (channel, direction, user_id, user_display, text, thread_id, mission_id, session_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    channel,
                    direction,
                    user_id,
                    user_display,
                    text,
                    thread_id,
                    mission_id,
                    session_id,
                )
        except Exception as exc:
            log.warning("router.persist_failed", direction=direction, error=str(exc))


def _parse_approval_channels() -> list[str]:
    raw = os.getenv("APPROVAL_CHANNELS", "telegram,web")
    return [c.strip() for c in raw.split(",") if c.strip()]
