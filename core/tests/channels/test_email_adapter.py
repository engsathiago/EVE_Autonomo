"""Testes do EmailAdapter — IMAP IDLE, SMTP, threading (C7-Email, C11)."""

from __future__ import annotations

import email
import email.message
import email.policy
from unittest.mock import AsyncMock, patch

import pytest

from agent.channels.base import ConfigError, IncomingMessage, OutgoingMessage
from agent.channels.email_adapter import EmailAdapter, _extract_body, _mask_email


def _make_adapter(
    allowlist: set[str] | None = None,
    router=None,
) -> EmailAdapter:
    return EmailAdapter(
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        user="bot@example.com",
        password="secret",
        allowlist=allowlist or {"user@example.com"},
        router=router,
    )


def _make_email(headers: dict, body: str = "texto de teste") -> email.message.Message:
    parts = [f"{k}: {v}" for k, v in headers.items()] + ["", body]
    return email.message_from_string("\r\n".join(parts), policy=email.policy.default)


# ── Construção ────────────────────────────────────────────────────────────────


def test_from_env_raises_config_error_on_missing_vars(monkeypatch):
    """from_env() levanta ConfigError se variáveis obrigatórias faltam."""
    monkeypatch.delenv("EMAIL_IMAP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_USER", raising=False)
    monkeypatch.delenv("EMAIL_PASS", raising=False)
    monkeypatch.delenv("EMAIL_FROM_ALLOWLIST", raising=False)
    with pytest.raises(ConfigError):
        EmailAdapter.from_env()


def test_from_env_raises_config_error_on_empty_allowlist(monkeypatch):
    """from_env() levanta ConfigError se EMAIL_FROM_ALLOWLIST está vazio."""
    monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("EMAIL_USER", "bot@example.com")
    monkeypatch.setenv("EMAIL_PASS", "pass")
    monkeypatch.setenv("EMAIL_FROM_ALLOWLIST", "")
    with pytest.raises(ConfigError):
        EmailAdapter.from_env()


def test_adapter_name():
    assert _make_adapter().name == "email"


# ── Autorização ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_authorized_true_for_listed_email():
    adapter = _make_adapter(allowlist={"user@example.com"})
    assert await adapter.is_authorized("user@example.com") is True


@pytest.mark.asyncio
async def test_is_authorized_false_for_unlisted():
    adapter = _make_adapter(allowlist={"user@example.com"})
    assert await adapter.is_authorized("other@example.com") is False


@pytest.mark.asyncio
async def test_is_authorized_case_insensitive():
    adapter = _make_adapter(allowlist={"user@example.com"})
    assert await adapter.is_authorized("USER@EXAMPLE.COM") is True


# ── _process_email: encaminhamento correto ────────────────────────────────────


@pytest.mark.asyncio
async def test_process_email_reaches_router():
    """Email válido com prefixo [agent] chega ao router."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage):
            received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    msg = _make_email(
        {
            "From": "user@example.com",
            "To": "bot@example.com",
            "Subject": "[agent] verificar status",
            "Message-ID": "<test@example.com>",
        }
    )
    await adapter._process_email(msg)

    assert len(received) == 1
    assert received[0].channel == "email"
    assert received[0].user_id == "user@example.com"
    assert "verificar status" in received[0].text


@pytest.mark.asyncio
async def test_process_email_without_prefix_is_ignored():
    """Email sem prefixo [agent] no subject é descartado."""
    received = []

    class FakeRouter:
        async def handle(self, msg):
            received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    msg = _make_email(
        {
            "From": "user@example.com",
            "Subject": "assunto sem prefixo",
            "Message-ID": "<x@x.com>",
        }
    )
    await adapter._process_email(msg)
    assert received == []


@pytest.mark.asyncio
async def test_process_email_preserves_thread_id():
    """Message-ID é propagado como thread_id para In-Reply-To na resposta."""
    received = []

    class FakeRouter:
        async def handle(self, msg: IncomingMessage):
            received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    msg = _make_email(
        {
            "From": "user@example.com",
            "Subject": "[agent] qual é o status?",
            "Message-ID": "<original-id@example.com>",
        }
    )
    await adapter._process_email(msg)

    assert received[0].thread_id == "<original-id@example.com>"


@pytest.mark.asyncio
async def test_attachment_email_gets_warning():
    """Email com anexo recebe aviso e não chega ao router."""
    received = []
    sent_responses = []

    class FakeRouter:
        async def handle(self, msg):
            received.append(msg)

    adapter = _make_adapter(router=FakeRouter())
    adapter.send = AsyncMock(side_effect=lambda uid, out: sent_responses.append(out))

    # Cria email multipart com anexo
    import email.mime.base
    import email.mime.multipart
    import email.mime.text

    multipart = email.mime.multipart.MIMEMultipart()
    multipart["From"] = "user@example.com"
    multipart["Subject"] = "[agent] com anexo"
    multipart["Message-ID"] = "<attach@example.com>"
    multipart.attach(email.mime.text.MIMEText("texto"))
    part = email.mime.base.MIMEBase("application", "octet-stream")
    part["Content-Disposition"] = 'attachment; filename="file.pdf"'
    multipart.attach(part)

    await adapter._process_email(multipart)

    assert received == [], "email com anexo não deve chegar ao router"
    assert len(sent_responses) == 1, "deve enviar aviso sobre anexo"
    assert "Anexos" in sent_responses[0].text


# ── C7-Email: threading (In-Reply-To) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_sets_in_reply_to_header():
    """send() com thread_id inclui In-Reply-To correto no email enviado."""
    sent_msgs = []

    class FakeSMTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def login(self, *a):
            pass

        async def send_message(self, msg):
            sent_msgs.append(msg)

    adapter = _make_adapter()

    with patch("aiosmtplib.SMTP", return_value=FakeSMTP()):
        await adapter.send(
            "user@example.com",
            OutgoingMessage(text="resposta", thread_id="<original@example.com>"),
        )

    assert len(sent_msgs) == 1
    assert sent_msgs[0]["In-Reply-To"] == "<original@example.com>"
    assert sent_msgs[0]["References"] == "<original@example.com>"


@pytest.mark.asyncio
async def test_send_includes_auto_submitted_header():
    """send() sempre inclui Auto-Submitted: auto-generated para evitar loops."""
    sent_msgs = []

    class FakeSMTP:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def login(self, *a):
            pass

        async def send_message(self, msg):
            sent_msgs.append(msg)

    adapter = _make_adapter()

    with patch("aiosmtplib.SMTP", return_value=FakeSMTP()):
        await adapter.send("user@example.com", OutgoingMessage(text="ok"))

    assert sent_msgs[0]["Auto-Submitted"] == "auto-generated"


# ── Helpers ───────────────────────────────────────────────────────────────────


def test_mask_email_normal():
    # "thiago" tem 6 chars → t + 4 asteriscos + o
    assert _mask_email("thiago@gmail.com") == "t****o@gmail.com"


def test_mask_email_short_local():
    assert _mask_email("ab@gmail.com") == "a***@gmail.com"


def test_mask_email_no_domain():
    assert _mask_email("nodomain") == "***"


def test_extract_body_plain_text():
    msg = _make_email({"Content-Type": "text/plain"}, body="corpo aqui")
    assert "corpo aqui" in _extract_body(msg)


def test_extract_body_strips_html():
    msg = email.message_from_string(
        "Content-Type: text/html\r\n\r\n<p>hello <b>world</b></p>",
        policy=email.policy.default,
    )
    body = _extract_body(msg)
    assert "hello" in body
    assert "<p>" not in body
