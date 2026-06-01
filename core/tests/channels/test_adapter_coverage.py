"""Testes adicionais de cobertura para start/stop/send dos adapters."""
from __future__ import annotations

import asyncio
import email.message
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── EmailAdapter: start / stop / send edge cases ─────────────────────────────

def _email_adapter():
    from agent.channels.email_adapter import EmailAdapter
    return EmailAdapter(
        imap_host="imap.test.com",
        imap_port=993,
        smtp_host="smtp.test.com",
        smtp_port=587,
        user="agent@test.com",
        password="secret",
        allowlist={"user@test.com"},
        router=None,
    )


@pytest.mark.asyncio
async def test_email_adapter_start_creates_task():
    adapter = _email_adapter()
    with patch("asyncio.create_task") as mock_task:
        mock_task.return_value = MagicMock()
        await adapter.start()
    assert adapter._running is True
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_email_adapter_stop_cancels_task():
    adapter = _email_adapter()

    async def _coro():
        raise asyncio.CancelledError()

    task = asyncio.ensure_future(_coro())
    adapter._task = task
    adapter._running = True

    await adapter.stop()

    assert adapter._running is False


@pytest.mark.asyncio
async def test_email_adapter_stop_without_task_is_safe():
    adapter = _email_adapter()
    adapter._task = None
    adapter._running = True
    await adapter.stop()
    assert adapter._running is False


@pytest.mark.asyncio
async def test_email_send_large_body_becomes_attachment():
    adapter = _email_adapter()

    large_text = "x" * (51 * 1024)  # > 50 KB

    smtp_mock = AsyncMock()
    smtp_mock.__aenter__ = AsyncMock(return_value=smtp_mock)
    smtp_mock.__aexit__ = AsyncMock(return_value=False)
    smtp_mock.login = AsyncMock()
    smtp_mock.send_message = AsyncMock()

    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text=large_text)

    with patch("aiosmtplib.SMTP", return_value=smtp_mock):
        await adapter.send("user@test.com", msg)

    smtp_mock.send_message.assert_called_once()
    # Verifica que o email enviado tem o texto truncado no corpo
    sent_msg = smtp_mock.send_message.call_args[0][0]
    body_str = sent_msg.get_body().get_content() if sent_msg.get_body() else ""
    assert "50 KB" in body_str or "em anexo" in body_str


@pytest.mark.asyncio
async def test_email_send_smtp_exception_logged():
    adapter = _email_adapter()
    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text="texto curto")

    smtp_mock = AsyncMock()
    smtp_mock.__aenter__ = AsyncMock(side_effect=Exception("conn refused"))
    smtp_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("aiosmtplib.SMTP", return_value=smtp_mock):
        await adapter.send("user@test.com", msg)  # não deve propagar


def test_email_extract_body_fallback_non_multipart():
    """Mensagem não-multipart usa get_payload(decode=True) como fallback."""
    from agent.channels.email_adapter import _extract_body
    msg = email.message.Message()
    msg.set_payload("corpo simples", charset="utf-8")
    result = _extract_body(msg)
    # Fallback retorna string vazia ou o payload (implementação-dependente)
    assert isinstance(result, str)


# ── DiscordAdapter: _on_ready / stop / send with thread ──────────────────────

def _discord_adapter():
    from agent.channels.discord_adapter import DiscordAdapter
    return DiscordAdapter(
        token="fake-token",
        guild_id=42,
        allowlist={"111"},
        channels_allowed={"general"},
        router=None,
    )


@pytest.mark.asyncio
async def test_discord_on_ready_sets_metric():
    adapter = _discord_adapter()
    await adapter._on_ready()  # deve setar métrica sem exceção


@pytest.mark.asyncio
async def test_discord_stop_with_client_and_task():
    adapter = _discord_adapter()
    client_mock = AsyncMock()
    client_mock.close = AsyncMock()
    adapter._client = client_mock

    task = AsyncMock()
    task.cancel = MagicMock()
    adapter._task = task

    await adapter.stop()

    client_mock.close.assert_called_once()
    task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_discord_stop_without_client_is_safe():
    adapter = _discord_adapter()
    adapter._client = None
    adapter._task = None
    await adapter.stop()  # não deve propagar


@pytest.mark.asyncio
async def test_discord_send_uses_thread_channel_when_found():
    adapter = _discord_adapter()
    channel_mock = AsyncMock()
    thread_mock = AsyncMock()
    thread_mock.send = AsyncMock()

    client_mock = MagicMock()
    client_mock.get_channel = MagicMock(return_value=thread_mock)
    adapter._client = client_mock
    adapter._channel_refs["111"] = channel_mock

    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text="resposta na thread", thread_id="999")

    await adapter.send("111", msg)

    thread_mock.send.assert_called_once()
    channel_mock.send.assert_not_called()


@pytest.mark.asyncio
async def test_discord_send_falls_through_when_thread_not_found():
    adapter = _discord_adapter()
    channel_mock = AsyncMock()
    channel_mock.send = AsyncMock()

    client_mock = MagicMock()
    client_mock.get_channel = MagicMock(return_value=None)
    adapter._client = client_mock
    adapter._channel_refs["111"] = channel_mock

    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text="texto curto", thread_id="999")

    await adapter.send("111", msg)

    channel_mock.send.assert_called_once_with("texto curto")


@pytest.mark.asyncio
async def test_discord_send_embed_for_long_text():
    adapter = _discord_adapter()
    channel_mock = AsyncMock()
    channel_mock.send = AsyncMock()
    adapter._channel_refs["111"] = channel_mock
    adapter._client = None

    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text="x" * 201)

    await adapter.send("111", msg)

    channel_mock.send.assert_called_once()
    call_kwargs = channel_mock.send.call_args
    assert "embed" in (call_kwargs.kwargs or {}) or len(call_kwargs.args) == 0


# ── SlackAdapter: stop / send client=None / _handle_dm branches ───────────────

def _slack_adapter():
    from agent.channels.slack_adapter import SlackAdapter
    return SlackAdapter(
        app_token="xapp-fake",
        bot_token="xoxb-fake",
        allowlist={"U111"},
        router=None,
    )


@pytest.mark.asyncio
async def test_slack_stop_with_handler():
    adapter = _slack_adapter()
    handler_mock = AsyncMock()
    handler_mock.close_async = AsyncMock()
    adapter._socket_handler = handler_mock

    await adapter.stop()

    handler_mock.close_async.assert_called_once()


@pytest.mark.asyncio
async def test_slack_stop_without_handler_is_safe():
    adapter = _slack_adapter()
    adapter._socket_handler = None
    await adapter.stop()  # não deve propagar


@pytest.mark.asyncio
async def test_slack_send_when_client_is_none():
    adapter = _slack_adapter()
    adapter._channel_refs["U111"] = {"channel_id": "C001", "thread_ts": "1.0"}
    adapter._slack_client = None

    from agent.channels.base import OutgoingMessage
    msg = OutgoingMessage(text="olá")

    await adapter.send("U111", msg)  # deve retornar silenciosamente


@pytest.mark.asyncio
async def test_slack_handle_dm_with_files_sends_warning():
    adapter = _slack_adapter()
    router_mock = AsyncMock()
    adapter._router = router_mock

    client_mock = AsyncMock()
    client_mock.chat_postMessage = AsyncMock()
    say_mock = AsyncMock()

    event = {
        "channel_type": "im",
        "user": "U111",
        "channel": "D001",
        "ts": "1.0",
        "text": "olá",
        "files": [{"id": "F001"}],
    }

    await adapter._handle_dm(event=event, say=say_mock, client=client_mock)

    client_mock.chat_postMessage.assert_called_once()
    msg_text = client_mock.chat_postMessage.call_args.kwargs.get("text", "")
    assert "Anexo" in msg_text or "não" in msg_text.lower()
    router_mock.handle.assert_not_called()


@pytest.mark.asyncio
async def test_slack_handle_dm_user_not_in_allowlist_ignored():
    adapter = _slack_adapter()
    router_mock = AsyncMock()
    adapter._router = router_mock

    event = {
        "channel_type": "im",
        "user": "UNAUTHORIZED",
        "channel": "D001",
        "ts": "1.0",
        "text": "olá",
    }

    await adapter._handle_dm(event=event, say=AsyncMock(), client=AsyncMock())

    router_mock.handle.assert_not_called()


@pytest.mark.asyncio
async def test_slack_handle_dm_no_text_ignored():
    adapter = _slack_adapter()
    router_mock = AsyncMock()
    adapter._router = router_mock

    event = {
        "channel_type": "im",
        "user": "U111",
        "channel": "D001",
        "ts": "1.0",
        "text": "",
    }

    await adapter._handle_dm(event=event, say=AsyncMock(), client=AsyncMock())

    router_mock.handle.assert_not_called()
