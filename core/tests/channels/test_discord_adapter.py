"""Testes do DiscordAdapter — allowlist, on_message, embeds, threading (C7-Discord)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.channels.base import ConfigError, IncomingMessage, OutgoingMessage
from agent.channels.discord_adapter import DiscordAdapter, _parse_allowlist


# ── Construção ────────────────────────────────────────────────────────────────

def test_no_allowlist_raises_config_error():
    with pytest.raises(ConfigError):
        DiscordAdapter(token="tok", guild_id=1, allowlist=set(), channels_allowed=set())


def test_from_env_raises_on_missing_token(monkeypatch):
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("DISCORD_USER_ALLOWLIST", "111")
    with pytest.raises(ConfigError):
        DiscordAdapter.from_env()


def test_from_env_raises_on_empty_allowlist(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123")
    monkeypatch.setenv("DISCORD_USER_ALLOWLIST", "")
    with pytest.raises(ConfigError):
        DiscordAdapter.from_env()


def test_adapter_name():
    adapter = DiscordAdapter(token="t", guild_id=1, allowlist={"111"}, channels_allowed=set())
    assert adapter.name == "discord"


def test_parse_allowlist_csv():
    result = _parse_allowlist("111,222, 333 ")
    assert result == {"111", "222", "333"}


# ── Autorização ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_authorized_true_for_listed():
    adapter = DiscordAdapter(token="t", guild_id=1, allowlist={"111"}, channels_allowed=set())
    assert await adapter.is_authorized("111") is True


@pytest.mark.asyncio
async def test_is_authorized_false_for_unlisted():
    adapter = DiscordAdapter(token="t", guild_id=1, allowlist={"111"}, channels_allowed=set())
    assert await adapter.is_authorized("999") is False


# ── on_message ────────────────────────────────────────────────────────────────

def _make_adapter(allowlist=None, channels_allowed=None, router=None):
    return DiscordAdapter(
        token="tok",
        guild_id=42,
        allowlist=allowlist or {"111"},
        channels_allowed=channels_allowed or set(),
        router=router,
    )


def _make_message(
    user_id=111,
    bot=False,
    content="olá",
    guild_id=42,
    channel_name="general",
    is_dm=False,
    attachments=None,
    mentions=None,
):
    import discord
    msg = MagicMock()
    msg.author.id = user_id
    msg.author.display_name = "TestUser"
    msg.author.bot = bot
    msg.content = content
    msg.attachments = attachments or []
    msg.id = 99
    msg.channel.send = AsyncMock()
    msg.channel.create_thread = AsyncMock(
        return_value=MagicMock(send=AsyncMock(), id=555)
    )
    if is_dm:
        msg.channel = MagicMock(spec=discord.DMChannel)
        msg.channel.send = AsyncMock()
        msg.guild = None
    else:
        msg.guild = MagicMock()
        msg.guild.id = guild_id
        msg.channel.name = channel_name
    msg.mentions = mentions or []
    return msg


@pytest.mark.asyncio
async def test_bot_message_is_ignored():
    """Mensagens de bots são ignoradas."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    adapter._client = MagicMock()
    adapter._client.user = MagicMock(id=9999)

    msg = _make_message(bot=True, content="sou um bot")
    await adapter._on_message(msg)
    assert received == []


@pytest.mark.asyncio
async def test_message_from_wrong_guild_is_ignored():
    """Mensagens de guild diferente do configurado são ignoradas."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    adapter._client = MagicMock()
    adapter._client.user = MagicMock(id=9999, mention="<@9999>")

    msg = _make_message(guild_id=999, content="<@9999> oi")
    msg.mentions = [adapter._client.user]
    await adapter._on_message(msg)
    assert received == []


@pytest.mark.asyncio
async def test_mention_triggers_response():
    """Menção direta ao bot aciona o router."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    bot_user = MagicMock(id=9999, mention="<@9999>")
    adapter._client = MagicMock()
    adapter._client.user = bot_user

    msg = _make_message(content="<@9999> qual é o status?")
    msg.mentions = [bot_user]
    await adapter._on_message(msg)

    assert len(received) == 1
    assert received[0].channel == "discord"
    assert "status" in received[0].text


@pytest.mark.asyncio
async def test_channel_allowed_triggers_response():
    """Mensagem em canal autorizado aciona o router (sem menção)."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage): received.append(msg)

    adapter = _make_adapter(channels_allowed={"agent-control"}, router=FakeRouter())
    adapter._client = MagicMock()
    adapter._client.user = MagicMock(id=9999)

    msg = _make_message(content="oi", channel_name="agent-control")
    msg.mentions = []
    await adapter._on_message(msg)

    assert len(received) == 1


@pytest.mark.asyncio
async def test_attachment_gets_warning():
    """Email com anexo recebe aviso sem chegar ao router."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    bot_user = MagicMock(id=9999)
    adapter._client = MagicMock()
    adapter._client.user = bot_user

    msg = _make_message(content="<@9999> texto com anexo", attachments=["arquivo.pdf"])
    msg.mentions = [bot_user]
    await adapter._on_message(msg)

    msg.channel.send.assert_called_once()
    assert received == []


# ── send(): embeds para textos longos ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_short_text_without_embed():
    """Texto curto (≤ 200 chars) é enviado como texto simples."""
    adapter = _make_adapter()
    channel = MagicMock()
    channel.send = AsyncMock()
    adapter._channel_refs["111"] = channel

    await adapter.send("111", OutgoingMessage(text="resposta curta"))

    channel.send.assert_called_once()
    call_kwargs = channel.send.call_args
    # Não deve ter embed=... quando texto é curto
    assert "embed" not in (call_kwargs.kwargs or {})


@pytest.mark.asyncio
async def test_send_long_text_uses_embed():
    """Texto longo (> 200 chars) vira embed."""
    import discord
    adapter = _make_adapter()
    channel = MagicMock()
    channel.send = AsyncMock()
    adapter._channel_refs["111"] = channel

    long_text = "A" * 201
    await adapter.send("111", OutgoingMessage(text=long_text))

    channel.send.assert_called_once()
    _, kwargs = channel.send.call_args
    assert "embed" in kwargs
    assert isinstance(kwargs["embed"], discord.Embed)


@pytest.mark.asyncio
async def test_send_to_unknown_user_is_noop():
    """send() para user sem referência de canal não levanta exceção."""
    adapter = _make_adapter()
    await adapter.send("UNKNOWN", OutgoingMessage(text="oi"))  # não deve levantar
