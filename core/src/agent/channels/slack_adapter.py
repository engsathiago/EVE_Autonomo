"""SlackAdapter (F12) — slack-bolt async em Socket Mode (sem ngrok, sem porta aberta).

Regras:
- Allowlist obrigatória (SLACK_USER_ALLOWLIST). ConfigError sem lista.
- Socket Mode: Slack abre WS reverso — não expõe porta no servidor.
- Escuta app_mention e message.im (DMs).
- Responde sempre na thread da mensagem original (thread_ts).
- Respostas > 4000 chars são enviadas como arquivo .txt (Slack limit).
- Tokens nunca logados (redact no logger global).
"""

from __future__ import annotations

import os
from typing import Any

from agent.channels import metrics as ch_metrics
from agent.channels.base import ChannelAdapter, ConfigError, IncomingMessage, OutgoingMessage
from agent.observability.logger import get_logger

log = get_logger(__name__)

_MAX_TEXT_LEN = 4000  # chars — acima disso, arquivo .txt


def _parse_allowlist(raw: str) -> set[str]:
    return {uid.strip() for uid in raw.split(",") if uid.strip()}


class SlackAdapter(ChannelAdapter):
    """Adapta Slack (Socket Mode) ao ChannelRouter."""

    name = "slack"

    def __init__(
        self,
        app_token: str,
        bot_token: str,
        allowlist: set[str],
        router: Any | None = None,
    ) -> None:
        if not allowlist:
            raise ConfigError(
                "SLACK_USER_ALLOWLIST é obrigatório. Sem allowlist o adapter não sobe (regra de segurança)."
            )
        self._app_token = app_token
        self._bot_token = bot_token
        self._allowlist = allowlist
        self._router = router
        self._app: Any | None = None
        self._socket_handler: Any | None = None
        self._slack_client: Any | None = None
        # Mapa user_id → {"channel_id": str, "thread_ts": str | None}
        self._channel_refs: dict[str, dict[str, str | None]] = {}

    @classmethod
    def from_env(cls, router: Any | None = None) -> SlackAdapter:
        app_token = os.getenv("SLACK_APP_TOKEN", "")
        bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        allowlist_raw = os.getenv("SLACK_USER_ALLOWLIST", "")

        missing = [
            k
            for k, v in {
                "SLACK_APP_TOKEN": app_token,
                "SLACK_BOT_TOKEN": bot_token,
                "SLACK_USER_ALLOWLIST": allowlist_raw,
            }.items()
            if not v
        ]
        if missing:
            raise ConfigError(f"Variáveis Slack ausentes: {', '.join(missing)}")

        allowlist = _parse_allowlist(allowlist_raw)
        if not allowlist:
            raise ConfigError("SLACK_USER_ALLOWLIST está vazio — adapter não sobe.")

        return cls(
            app_token=app_token,
            bot_token=bot_token,
            allowlist=allowlist,
            router=router,
        )

    def set_router(self, router: Any) -> None:
        self._router = router

    async def start(self) -> None:
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        self._app = AsyncApp(token=self._bot_token)
        self._slack_client = self._app.client

        # Registra handlers
        self._app.event("app_mention")(self._handle_mention)
        self._app.event("message")(self._handle_dm)

        self._socket_handler = AsyncSocketModeHandler(self._app, self._app_token)
        await self._socket_handler.connect_async()
        ch_metrics.connection_status.labels(channel="slack").set(1)
        log.info("slack.adapter.started")

    async def stop(self) -> None:
        if self._socket_handler:
            try:
                await self._socket_handler.close_async()
            except Exception:
                pass
        ch_metrics.connection_status.labels(channel="slack").set(0)
        log.info("slack.adapter.stopped")

    async def send(self, user_id: str, msg: OutgoingMessage) -> None:
        """Envia resposta no canal/thread correto."""
        ref = self._channel_refs.get(user_id)
        if ref is None:
            log.warning("slack.send.no_channel_ref", user_id=user_id)
            return

        channel_id = ref["channel_id"]
        thread_ts = msg.thread_id or ref.get("thread_ts")
        text = msg.text
        client = self._slack_client

        if client is None:
            return

        if len(text) > _MAX_TEXT_LEN:
            # Envia como arquivo .txt
            try:
                await client.files_upload_v2(
                    channel=channel_id,
                    content=text,
                    filename="response.txt",
                    title="Resposta do agente",
                    thread_ts=thread_ts,
                )
            except Exception as exc:
                log.warning("slack.file_upload_failed", error=str(exc))
                # Fallback: truncado
                await client.chat_postMessage(
                    channel=channel_id,
                    text=text[:_MAX_TEXT_LEN] + "\n…(truncado)",
                    thread_ts=thread_ts,
                )
            return

        await client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
        )

    async def is_authorized(self, user_id: str) -> bool:
        return user_id in self._allowlist

    # ── Event handlers ───────────────────────────────────────────────────────

    async def _handle_mention(self, event: dict, say: Any, client: Any) -> None:
        """Handler de app_mention."""
        user_id = event.get("user", "")
        if not user_id or user_id not in self._allowlist:
            return

        channel_id = event.get("channel", "")
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts") or ts
        text = event.get("text", "")

        # Remove menção do bot do texto
        text = _strip_bot_mention(text)

        if not text:
            return

        self._channel_refs[user_id] = {"channel_id": channel_id, "thread_ts": thread_ts}

        # Descarta mensagem com arquivos
        if event.get("files"):
            await client.chat_postMessage(
                channel=channel_id,
                text="Anexos não são processados nesta versão.",
                thread_ts=thread_ts,
            )
            return

        incoming = IncomingMessage(
            channel="slack",
            user_id=user_id,
            user_display=user_id,
            text=text,
            thread_id=thread_ts,
            raw={"channel": channel_id, "ts": ts},
        )

        if self._router:
            await self._router.handle(incoming)

    async def _handle_dm(self, event: dict, say: Any, client: Any) -> None:
        """Handler de DMs (message.im)."""
        # Ignora mensagens de bot (subtype=bot_message) e de si mesmo
        if event.get("subtype") == "bot_message":
            return
        if event.get("bot_id"):
            return

        channel_type = event.get("channel_type", "")
        if channel_type != "im":
            return  # só processa DMs

        user_id = event.get("user", "")
        if not user_id or user_id not in self._allowlist:
            return

        channel_id = event.get("channel", "")
        ts = event.get("ts", "")
        text = event.get("text", "")

        if not text:
            return

        self._channel_refs[user_id] = {"channel_id": channel_id, "thread_ts": ts}

        if event.get("files"):
            await client.chat_postMessage(
                channel=channel_id,
                text="Anexos não são processados nesta versão.",
                thread_ts=ts,
            )
            return

        incoming = IncomingMessage(
            channel="slack",
            user_id=user_id,
            user_display=user_id,
            text=text,
            thread_id=ts,
            raw={"channel": channel_id, "ts": ts},
        )

        if self._router:
            await self._router.handle(incoming)


def _strip_bot_mention(text: str) -> str:
    """Remove padrão <@BOTID> do início do texto."""
    import re

    return re.sub(r"^<@[A-Z0-9]+>\s*", "", text).strip()
