"""TDD — Gating de aprovação por canal (C6).

/approve e /deny só funcionam em canais listados em APPROVAL_CHANNELS.
"""
from __future__ import annotations

import pytest

from agent.channels.base import IncomingMessage


def _msg(channel: str = "discord", user_id: str = "U1", text: str = "/approve abc-123") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id=user_id,
        user_display="TestUser",
        text=text,
    )


# ── Gating por canal ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_blocked_on_unauthorized_channel():
    """C6: /approve em canal não autorizado retorna mensagem de bloqueio."""
    from agent.channels.commands import dispatch_command

    result = await dispatch_command(
        text="/approve abc-123",
        msg=_msg(channel="discord"),
        session_id="discord:U1",
        orchestrator=None,
        approval_manager=None,
        approval_channels={"telegram", "web"},  # discord NÃO autorizado
        db_pool=None,
    )

    assert "não está autorizado" in result.lower() or "não autorizado" in result.lower()
    assert "discord" in result.lower()


@pytest.mark.asyncio
async def test_deny_blocked_on_unauthorized_channel():
    """C6: /deny em canal não autorizado também retorna bloqueio."""
    from agent.channels.commands import dispatch_command

    result = await dispatch_command(
        text="/deny abc-123",
        msg=_msg(channel="slack"),
        session_id="slack:U1",
        orchestrator=None,
        approval_manager=None,
        approval_channels={"telegram", "web"},  # slack NÃO autorizado
        db_pool=None,
    )

    assert "não está autorizado" in result.lower() or "não autorizado" in result.lower()


@pytest.mark.asyncio
async def test_approve_allowed_on_authorized_channel():
    """C6: /approve em canal autorizado chama approval_manager.decide()."""
    from unittest.mock import AsyncMock

    from agent.channels.commands import dispatch_command

    approval_manager = AsyncMock()
    approval_manager.decide = AsyncMock(return_value=None)

    # Patch para simular que decide() não levanta exceção
    result = await dispatch_command(
        text="/approve abc-123",
        msg=_msg(channel="telegram"),
        session_id="telegram:U1",
        orchestrator=None,
        approval_manager=approval_manager,
        approval_channels={"telegram", "web"},  # telegram autorizado
        db_pool=None,
    )

    approval_manager.decide.assert_called_once_with(
        approval_id="abc-123",
        decision="approve",
        decided_by="telegram:U1",
    )
    assert "aprovada" in result.lower()


@pytest.mark.asyncio
async def test_deny_allowed_on_authorized_channel():
    """C6: /deny em canal autorizado chama approval_manager.decide() com reject."""
    from unittest.mock import AsyncMock

    from agent.channels.commands import dispatch_command

    approval_manager = AsyncMock()
    approval_manager.decide = AsyncMock(return_value=None)

    result = await dispatch_command(
        text="/deny xyz-456",
        msg=_msg(channel="web"),
        session_id="web:U1",
        orchestrator=None,
        approval_manager=approval_manager,
        approval_channels={"telegram", "web"},
        db_pool=None,
    )

    approval_manager.decide.assert_called_once_with(
        approval_id="xyz-456",
        decision="reject",
        decided_by="web:U1",
    )
    assert "negada" in result.lower()


@pytest.mark.asyncio
async def test_approval_channels_default_is_telegram_and_web():
    """APPROVAL_CHANNELS default deve incluir telegram e web, não discord/slack."""
    import os
    from unittest.mock import patch

    # Sem variável setada → default telegram,web
    with patch.dict(os.environ, {}, clear=True):
        # Remove a variável se existir
        env = dict(os.environ)
        env.pop("APPROVAL_CHANNELS", None)
        with patch.dict(os.environ, env, clear=True):
            from agent.channels.router import _parse_approval_channels
            channels = _parse_approval_channels()
            assert "telegram" in channels
            assert "web" in channels
            assert "discord" not in channels
            assert "slack" not in channels


@pytest.mark.asyncio
async def test_approve_without_id_returns_usage():
    """C6: /approve sem ID retorna mensagem de uso."""
    from agent.channels.commands import dispatch_command

    result = await dispatch_command(
        text="/approve",
        msg=_msg(channel="telegram"),
        session_id="telegram:U1",
        orchestrator=None,
        approval_manager=None,
        approval_channels={"telegram"},
        db_pool=None,
    )

    assert "uso" in result.lower() or "id" in result.lower()


# ── Comandos básicos ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_command_returns_help_text():
    """C6: /help retorna lista de comandos disponíveis."""
    from agent.channels.commands import dispatch_command

    result = await dispatch_command(
        text="/help",
        msg=_msg(channel="discord", text="/help"),
        session_id="discord:U1",
        orchestrator=None,
        approval_manager=None,
        approval_channels={"telegram"},
        db_pool=None,
    )

    assert "/mission" in result
    assert "/status" in result
    assert "/approve" in result


@pytest.mark.asyncio
async def test_unknown_command_returns_error():
    """Comando desconhecido retorna mensagem de erro com /help."""
    from agent.channels.commands import dispatch_command

    result = await dispatch_command(
        text="/xyzabc",
        msg=_msg(channel="discord", text="/xyzabc"),
        session_id="discord:U1",
        orchestrator=None,
        approval_manager=None,
        approval_channels=set(),
        db_pool=None,
    )

    assert "desconhecido" in result.lower() or "/help" in result
