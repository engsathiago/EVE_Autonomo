"""TDD — Anti-loop e Anti-spoof do EmailAdapter (C8, C9).

Escrito antes da implementação de _process_email.
"""
from __future__ import annotations

import email
import email.message
import email.policy

import pytest

from agent.channels.email_adapter import (
    EmailAdapter,
    _is_auto_reply,
    _spf_dkim_failed,
)


def _make_adapter(allowlist: set[str] | None = None) -> EmailAdapter:
    return EmailAdapter(
        imap_host="imap.example.com",
        imap_port=993,
        smtp_host="smtp.example.com",
        smtp_port=587,
        user="bot@example.com",
        password="app-password",
        allowlist=allowlist or {"user@example.com"},
    )


def _make_msg(headers: dict[str, str], body: str = "corpo do email") -> email.message.Message:
    raw_parts = [f"{k}: {v}" for k, v in headers.items()]
    raw_parts.append("")
    raw_parts.append(body)
    raw = "\r\n".join(raw_parts)
    return email.message_from_string(raw, policy=email.policy.default)


# ── C8: Anti-loop ─────────────────────────────────────────────────────────────

def test_auto_submitted_auto_replied_is_detected():
    """Header Auto-Submitted: auto-replied deve ser detectado como auto-resposta."""
    msg = _make_msg({"Auto-Submitted": "auto-replied"})
    assert _is_auto_reply(msg) is True


def test_auto_submitted_auto_generated_is_detected():
    """Header Auto-Submitted: auto-generated (ex: nossas próprias respostas) é detectado."""
    msg = _make_msg({"Auto-Submitted": "auto-generated"})
    assert _is_auto_reply(msg) is True


def test_auto_submitted_no_is_not_detected():
    """Auto-Submitted: no NÃO é marcado como auto-reply."""
    msg = _make_msg({"Auto-Submitted": "no"})
    assert _is_auto_reply(msg) is False


def test_x_autoreply_yes_is_detected():
    """X-Autoreply: yes deve ser detectado."""
    msg = _make_msg({"X-Autoreply": "yes"})
    assert _is_auto_reply(msg) is True


def test_x_autoreply_true_is_detected():
    """X-Autoreply: true deve ser detectado."""
    msg = _make_msg({"X-Autoreply": "true"})
    assert _is_auto_reply(msg) is True


def test_no_autoreply_headers_passes():
    """Email sem headers de auto-reply não é marcado."""
    msg = _make_msg({"From": "user@example.com", "Subject": "[agent] olá"})
    assert _is_auto_reply(msg) is False


@pytest.mark.asyncio
async def test_auto_reply_email_is_discarded_silently():
    """Email com Auto-Submitted não chega ao router (sem resposta ao remetente)."""
    router_called = []

    class FakeRouter:
        async def handle(self, msg):
            router_called.append(msg)

    adapter = _make_adapter()
    adapter.set_router(FakeRouter())

    msg = _make_msg({
        "From": "user@example.com",
        "To": "bot@example.com",
        "Subject": "[agent] status",
        "Auto-Submitted": "auto-replied",
        "Message-ID": "<id@example.com>",
    })
    await adapter._process_email(msg)

    assert router_called == [], "email auto-reply não deve chegar ao router"


# ── C9: Anti-spoof SPF/DKIM ───────────────────────────────────────────────────

def test_spf_fail_with_dkim_fail_is_rejected():
    """Authentication-Results com spf=fail e dkim=fail rejeita o email."""
    msg = _make_msg({"Authentication-Results": "mx.example.com; spf=fail; dkim=fail"})
    assert _spf_dkim_failed(msg) is True


def test_spf_softfail_with_dkim_fail_is_rejected():
    """softfail + dkim=fail também rejeita."""
    msg = _make_msg({"Authentication-Results": "mx.example.com; spf=softfail; dkim=none"})
    assert _spf_dkim_failed(msg) is True


def test_spf_pass_with_dkim_fail_passes():
    """SPF passa mas DKIM falha: permite (um pode ser legítimo)."""
    msg = _make_msg({"Authentication-Results": "mx.example.com; spf=pass; dkim=fail"})
    assert _spf_dkim_failed(msg) is False


def test_spf_fail_with_dkim_pass_passes():
    """SPF falha mas DKIM passa: permite."""
    msg = _make_msg({"Authentication-Results": "mx.example.com; spf=fail; dkim=pass"})
    assert _spf_dkim_failed(msg) is False


def test_no_auth_results_header_passes():
    """Sem Authentication-Results: não rejeita (não validado)."""
    msg = _make_msg({"From": "user@example.com"})
    assert _spf_dkim_failed(msg) is False


@pytest.mark.asyncio
async def test_spf_dkim_fail_email_is_discarded():
    """Email com spf=fail+dkim=fail não chega ao router."""
    router_called = []

    class FakeRouter:
        async def handle(self, msg):
            router_called.append(msg)

    adapter = _make_adapter()
    adapter.set_router(FakeRouter())

    msg = _make_msg({
        "From": "user@example.com",
        "To": "bot@example.com",
        "Subject": "[agent] status",
        "Authentication-Results": "mx.example.com; spf=fail; dkim=fail",
        "Message-ID": "<id@example.com>",
    })
    await adapter._process_email(msg)

    assert router_called == [], "email com spf/dkim fail não deve chegar ao router"


# ── Allowlist ─────────────────────────────────────────────────────────────────

def test_email_adapter_no_allowlist_raises_config_error():
    """Sem allowlist, EmailAdapter levanta ConfigError."""
    from agent.channels.base import ConfigError
    with pytest.raises(ConfigError):
        EmailAdapter(
            imap_host="x", imap_port=993,
            smtp_host="x", smtp_port=587,
            user="bot@x.com", password="pass",
            allowlist=set(),
        )


@pytest.mark.asyncio
async def test_unauthorized_sender_is_discarded():
    """Remetente fora da allowlist é descartado silenciosamente."""
    router_called = []

    class FakeRouter:
        async def handle(self, msg):
            router_called.append(msg)

    adapter = _make_adapter(allowlist={"allowed@example.com"})
    adapter.set_router(FakeRouter())

    msg = _make_msg({
        "From": "hacker@evil.com",
        "To": "bot@example.com",
        "Subject": "[agent] injeção de prompt",
        "Message-ID": "<hack@evil.com>",
    })
    await adapter._process_email(msg)

    assert router_called == []


def test_clean_email_passes_all_checks():
    """Email limpo (sem flags problemáticos) não é bloqueado pelas funções de check."""
    msg = _make_msg({
        "From": "user@example.com",
        "Authentication-Results": "mx.example.com; spf=pass; dkim=pass",
    })
    assert _is_auto_reply(msg) is False
    assert _spf_dkim_failed(msg) is False
