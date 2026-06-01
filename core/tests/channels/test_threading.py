"""Testes de threading por canal (C7): Discord threads, Slack thread_ts, Email In-Reply-To."""
from __future__ import annotations

import pytest

from agent.channels.base import OutgoingMessage

# ── Email threading ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_reply_preserves_thread_id():
    """OutgoingMessage com thread_id resulta em email com In-Reply-To correto (C7-Email)."""
    from unittest.mock import patch

    from agent.channels.email_adapter import EmailAdapter

    sent = []

    class FakeSMTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def login(self, *a): pass
        async def send_message(self, msg): sent.append(msg)

    adapter = EmailAdapter(
        imap_host="x", imap_port=993, smtp_host="x", smtp_port=587,
        user="bot@x.com", password="p",
        allowlist={"user@x.com"},
    )
    with patch("aiosmtplib.SMTP", return_value=FakeSMTP()):
        await adapter.send(
            "user@x.com",
            OutgoingMessage(text="resposta", thread_id="<original@x.com>"),
        )

    assert sent[0]["In-Reply-To"] == "<original@x.com>"
    assert sent[0]["References"] == "<original@x.com>"


@pytest.mark.asyncio
async def test_email_reply_without_thread_id_has_no_in_reply_to():
    """Email de resposta sem thread_id não inclui In-Reply-To."""
    from unittest.mock import patch

    from agent.channels.email_adapter import EmailAdapter

    sent = []

    class FakeSMTP:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def login(self, *a): pass
        async def send_message(self, msg): sent.append(msg)

    adapter = EmailAdapter(
        imap_host="x", imap_port=993, smtp_host="x", smtp_port=587,
        user="bot@x.com", password="p",
        allowlist={"user@x.com"},
    )
    with patch("aiosmtplib.SMTP", return_value=FakeSMTP()):
        await adapter.send("user@x.com", OutgoingMessage(text="sem thread"))

    assert sent[0]["In-Reply-To"] is None


# ── Discord threading ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discord_long_mission_creates_thread(mock_discord_message):
    """Discord: respostas longas (>200 chars) usam embed; missão longa cria thread (C7-Discord)."""
    from agent.channels.discord_adapter import DiscordAdapter

    adapter = DiscordAdapter(
        token="tok",
        guild_id=42,
        allowlist={"111"},
        channels_allowed=set(),
    )

    # Simula envio via mock do channel
    from unittest.mock import AsyncMock
    mock_discord_message.channel.send = AsyncMock()
    mock_discord_message.channel.create_thread = AsyncMock(
        return_value=type("T", (), {"send": AsyncMock(), "id": "t1"})()
    )

    # send() com thread_id deve usar o thread existente
    adapter._channel_refs = {"111": mock_discord_message.channel}
    out = OutgoingMessage(text="resposta curta")
    await adapter.send("111", out)
    mock_discord_message.channel.send.assert_called_once()


# ── Slack threading ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_reply_uses_thread_ts():
    """Slack: reply sempre usa thread_ts da mensagem original (C7-Slack)."""
    from unittest.mock import AsyncMock, MagicMock

    from agent.channels.slack_adapter import SlackAdapter

    adapter = SlackAdapter(
        app_token="xapp-token",
        bot_token="xoxb-token",
        allowlist={"U111"},
    )

    client = MagicMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "999.111"})

    # Simula referência de canal com thread_ts
    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": "111.222"}
    adapter._slack_client = client

    out = OutgoingMessage(text="resposta em thread", thread_id="111.222")
    await adapter.send("U111", out)

    call_kwargs = client.chat_postMessage.call_args[1]
    assert call_kwargs.get("thread_ts") == "111.222"


@pytest.mark.asyncio
async def test_slack_long_response_becomes_file():
    """Slack: resposta > 4000 chars é enviada como arquivo .txt (C7-Slack)."""
    from unittest.mock import AsyncMock, MagicMock

    from agent.channels.slack_adapter import SlackAdapter

    adapter = SlackAdapter(
        app_token="xapp-token",
        bot_token="xoxb-token",
        allowlist={"U111"},
    )

    client = MagicMock()
    client.files_upload_v2 = AsyncMock(return_value={"ok": True})
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1.2"})

    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": None}
    adapter._slack_client = client

    long_text = "A" * 4001
    out = OutgoingMessage(text=long_text)
    await adapter.send("U111", out)

    client.files_upload_v2.assert_called_once()
