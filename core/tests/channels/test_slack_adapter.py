"""Testes do SlackAdapter — allowlist, app_mention, DMs, thread_ts, Blocks (C7-Slack)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.channels.base import ConfigError, IncomingMessage, OutgoingMessage
from agent.channels.slack_adapter import SlackAdapter, _strip_bot_mention


def _make_adapter(allowlist=None, router=None):
    return SlackAdapter(
        app_token="xapp-token",
        bot_token="xoxb-token",
        allowlist=allowlist or {"U111"},
        router=router,
    )


def _make_client(post_return=None, upload_return=None):
    client = MagicMock()
    client.chat_postMessage = AsyncMock(return_value=post_return or {"ok": True, "ts": "1.1"})
    client.files_upload_v2 = AsyncMock(return_value=upload_return or {"ok": True})
    return client


# ── Construção ────────────────────────────────────────────────────────────────

def test_no_allowlist_raises_config_error():
    with pytest.raises(ConfigError):
        SlackAdapter(app_token="xapp", bot_token="xoxb", allowlist=set())


def test_from_env_raises_on_missing_tokens(monkeypatch):
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_USER_ALLOWLIST", raising=False)
    with pytest.raises(ConfigError):
        SlackAdapter.from_env()


def test_from_env_raises_on_empty_allowlist(monkeypatch):
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb")
    monkeypatch.setenv("SLACK_USER_ALLOWLIST", "")
    with pytest.raises(ConfigError):
        SlackAdapter.from_env()


def test_adapter_name():
    assert _make_adapter().name == "slack"


# ── Autorização ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_authorized_true():
    assert await _make_adapter(allowlist={"U111"}).is_authorized("U111") is True


@pytest.mark.asyncio
async def test_is_authorized_false():
    assert await _make_adapter(allowlist={"U111"}).is_authorized("U999") is False


# ── app_mention handler ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mention_reaches_router():
    """app_mention de user autorizado chega ao router."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    event = {
        "type": "app_mention",
        "user": "U111",
        "text": "<@BOTID> qual é o status?",
        "ts": "111.222",
        "channel": "C001",
    }
    await adapter._handle_mention(event, say=AsyncMock(), client=_make_client())

    assert len(received) == 1
    assert received[0].channel == "slack"
    assert "status" in received[0].text


@pytest.mark.asyncio
async def test_mention_from_unlisted_user_is_ignored():
    """app_mention de user não autorizado é ignorado."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(allowlist={"U111"}, router=FakeRouter())
    event = {
        "user": "U_BAD",
        "text": "<@BOTID> oi",
        "ts": "1.1",
        "channel": "C001",
    }
    await adapter._handle_mention(event, say=AsyncMock(), client=_make_client())
    assert received == []


@pytest.mark.asyncio
async def test_mention_sets_thread_ts():
    """app_mention registra thread_ts no channel_ref."""
    adapter = _make_adapter()

    event = {
        "user": "U111",
        "text": "<@BOTID> oi",
        "ts": "111.222",
        "channel": "C001",
        "thread_ts": "111.000",
    }
    await adapter._handle_mention(event, say=AsyncMock(), client=_make_client())

    assert adapter._channel_refs["U111"]["thread_ts"] == "111.000"


@pytest.mark.asyncio
async def test_mention_with_files_gets_warning():
    """Mensagem com arquivos recebe aviso, não chega ao router."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    client = _make_client()
    event = {
        "user": "U111",
        "text": "<@BOTID> com arquivo",
        "ts": "1.1",
        "channel": "C001",
        "files": [{"name": "doc.pdf"}],
    }
    await adapter._handle_mention(event, say=AsyncMock(), client=client)

    assert received == []
    client.chat_postMessage.assert_called_once()


# ── DM handler ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dm_reaches_router():
    """DM de user autorizado chega ao router."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    event = {
        "type": "message",
        "channel_type": "im",
        "user": "U111",
        "text": "olá do DM",
        "ts": "222.333",
        "channel": "D001",
    }
    await adapter._handle_dm(event, say=AsyncMock(), client=_make_client())

    assert len(received) == 1
    assert received[0].text == "olá do DM"


@pytest.mark.asyncio
async def test_bot_message_is_ignored():
    """Mensagem com bot_id é ignorada."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    event = {
        "subtype": "bot_message",
        "bot_id": "B001",
        "channel_type": "im",
        "text": "sou um bot",
        "ts": "1.1",
        "channel": "D001",
    }
    await adapter._handle_dm(event, say=AsyncMock(), client=_make_client())
    assert received == []


@pytest.mark.asyncio
async def test_non_dm_channel_is_ignored():
    """Evento message em canal público (não im) é ignorado."""
    received = []

    class FakeRouter:
        async def handle(self, msg): received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    event = {
        "channel_type": "channel",  # não é "im"
        "user": "U111",
        "text": "canal público",
        "ts": "1.1",
        "channel": "C001",
    }
    await adapter._handle_dm(event, say=AsyncMock(), client=_make_client())
    assert received == []


# ── send(): thread e arquivo para textos longos ───────────────────────────────

@pytest.mark.asyncio
async def test_send_uses_thread_ts():
    """send() usa thread_ts do channel_ref (C7-Slack)."""
    adapter = _make_adapter()
    client = _make_client()
    adapter._slack_client = client
    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": "111.222"}

    await adapter.send("U111", OutgoingMessage(text="resposta em thread", thread_id="111.222"))

    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args[1]
    assert call_kwargs["thread_ts"] == "111.222"


@pytest.mark.asyncio
async def test_send_long_text_uploads_file():
    """Texto > 4000 chars é enviado como arquivo .txt."""
    adapter = _make_adapter()
    client = _make_client()
    adapter._slack_client = client
    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": None}

    long_text = "X" * 4001
    await adapter.send("U111", OutgoingMessage(text=long_text))

    client.files_upload_v2.assert_called_once()
    client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_send_short_text_posts_message():
    """Texto curto (< 4000) vai como postMessage normal."""
    adapter = _make_adapter()
    client = _make_client()
    adapter._slack_client = client
    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": None}

    await adapter.send("U111", OutgoingMessage(text="resposta curta"))

    client.chat_postMessage.assert_called_once()
    client.files_upload_v2.assert_not_called()


@pytest.mark.asyncio
async def test_send_to_unknown_user_is_noop():
    """send() sem channel_ref não levanta exceção."""
    adapter = _make_adapter()
    adapter._slack_client = _make_client()
    await adapter.send("UNKNOWN", OutgoingMessage(text="oi"))  # não deve levantar


# ── Helpers ───────────────────────────────────────────────────────────────────

def test_strip_bot_mention_removes_prefix():
    assert _strip_bot_mention("<@U12345> status") == "status"


def test_strip_bot_mention_empty_after_removal():
    assert _strip_bot_mention("<@U12345>") == ""


def test_strip_bot_mention_no_mention():
    assert _strip_bot_mention("texto normal") == "texto normal"
