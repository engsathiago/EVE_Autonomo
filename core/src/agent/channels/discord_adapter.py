"""DiscordAdapter (F12) — discord.py, recebe mensagens e responde com embeds.

Regras:
- Allowlist obrigatória (DISCORD_USER_ALLOWLIST). ConfigError sem lista.
- Restrito ao DISCORD_GUILD_ID configurado — não responde em outros servidores.
- Responde se: mencionado diretamente, mensagem em DM, ou em canal listado em DISCORD_CHANNELS.
- Respostas > 200 chars viram embeds (Discord tem limite de 2000 chars por mensagem).
- Missões longas criam thread no canal de origem; atualizações ficam na thread.
- Nunca registra comandos slash na plataforma — só texto + menção.
- Tokens nunca logados (redact no logger global).
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import discord

from agent.channels.base import ChannelAdapter, ConfigError, IncomingMessage, OutgoingMessage
from agent.channels import metrics as ch_metrics
from agent.observability.logger import get_logger

log = get_logger(__name__)

_EMBED_THRESHOLD = 200   # chars — acima disso usa embed
_MAX_EMBED_LEN = 4096    # limite do Discord


def _parse_allowlist(raw: str) -> set[str]:
    return {uid.strip() for uid in raw.split(",") if uid.strip()}


class DiscordAdapter(ChannelAdapter):
    """Adapta Discord ao ChannelRouter."""

    name = "discord"

    def __init__(
        self,
        token: str,
        guild_id: int,
        allowlist: set[str],
        channels_allowed: set[str],
        router: Any | None = None,
    ) -> None:
        if not allowlist:
            raise ConfigError(
                "DISCORD_USER_ALLOWLIST é obrigatório. "
                "Sem allowlist o adapter não sobe (regra de segurança)."
            )
        self._token = token
        self._guild_id = guild_id
        self._allowlist = allowlist
        self._channels_allowed = channels_allowed
        self._router = router
        self._client: discord.Client | None = None
        self._task: asyncio.Task | None = None
        # Mapa user_id → discord.TextChannel para enviar respostas
        self._channel_refs: dict[str, Any] = {}

    @classmethod
    def from_env(cls, router: Any | None = None) -> "DiscordAdapter":
        token = os.getenv("DISCORD_BOT_TOKEN", "")
        guild_raw = os.getenv("DISCORD_GUILD_ID", "")
        allowlist_raw = os.getenv("DISCORD_USER_ALLOWLIST", "")

        missing = [k for k, v in {
            "DISCORD_BOT_TOKEN": token,
            "DISCORD_GUILD_ID": guild_raw,
            "DISCORD_USER_ALLOWLIST": allowlist_raw,
        }.items() if not v]
        if missing:
            raise ConfigError(f"Variáveis Discord ausentes: {', '.join(missing)}")

        allowlist = _parse_allowlist(allowlist_raw)
        if not allowlist:
            raise ConfigError("DISCORD_USER_ALLOWLIST está vazio — adapter não sobe.")

        channels_raw = os.getenv("DISCORD_CHANNELS", "")
        channels_allowed = {c.strip() for c in channels_raw.split(",") if c.strip()}

        return cls(
            token=token,
            guild_id=int(guild_raw),
            allowlist=allowlist,
            channels_allowed=channels_allowed,
            router=router,
        )

    def set_router(self, router: Any) -> None:
        self._router = router

    async def start(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self._client = discord.Client(intents=intents)
        self._client.event(self._on_ready)
        self._client.event(self._on_message)
        self._task = asyncio.create_task(self._client.start(self._token))
        log.info("discord.adapter.starting")

    async def stop(self) -> None:
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        ch_metrics.connection_status.labels(channel="discord").set(0)
        log.info("discord.adapter.stopped")

    async def send(self, user_id: str, msg: OutgoingMessage) -> None:
        """Envia resposta ao usuário pelo canal/DM/thread correto."""
        channel = self._channel_refs.get(user_id)
        if channel is None:
            log.warning("discord.send.no_channel_ref", user_id=user_id)
            return

        text = msg.text

        if msg.thread_id:
            # Tenta usar thread existente pelo ID
            if self._client:
                try:
                    thread = self._client.get_channel(int(msg.thread_id))
                    if thread:
                        await thread.send(text[:_MAX_EMBED_LEN])
                        return
                except Exception:
                    pass

        if len(text) > _EMBED_THRESHOLD:
            embed = discord.Embed(description=text[:_MAX_EMBED_LEN])
            await channel.send(embed=embed)
        else:
            await channel.send(text)

    async def is_authorized(self, user_id: str) -> bool:
        return str(user_id) in self._allowlist

    # ── Event handlers ───────────────────────────────────────────────────────

    async def _on_ready(self) -> None:
        ch_metrics.connection_status.labels(channel="discord").set(1)
        log.info("discord.ready", guild_id=self._guild_id)

    async def _on_message(self, message: discord.Message) -> None:
        if self._client is None:
            return

        # Ignora próprias mensagens e bots
        if message.author.bot:
            return

        user_id = str(message.author.id)

        # Valida guild
        if message.guild and message.guild.id != self._guild_id:
            return

        # Verifica se deve processar: mencionado, DM, ou canal autorizado
        is_dm = isinstance(message.channel, discord.DMChannel)
        bot_mentioned = self._client.user in message.mentions if self._client.user else False
        channel_allowed = (
            hasattr(message.channel, "name")
            and message.channel.name in self._channels_allowed
        )

        if not (bot_mentioned or is_dm or channel_allowed):
            return

        # Descarta anexos com aviso
        if message.attachments:
            await message.channel.send("Anexos não são processados nesta versão.")
            return

        # Salva referência do canal para resposta
        self._channel_refs[user_id] = message.channel

        text = message.content
        # Remove menção do bot do texto
        if self._client.user:
            mention = str(self._client.user.mention)
            text = text.replace(mention, "").strip()

        if not text:
            return

        incoming = IncomingMessage(
            channel="discord",
            user_id=user_id,
            user_display=message.author.display_name,
            text=text,
            thread_id=str(message.id),
            raw={"guild_id": message.guild.id if message.guild else None},
        )

        if self._router:
            await self._router.handle(incoming)
