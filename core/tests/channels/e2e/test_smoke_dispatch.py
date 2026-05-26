"""E2E smoke: cria missão via cada canal mockado, verifica resposta e persistência (C4, C5, C11)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.channels.base import IncomingMessage, OutgoingMessage
from agent.channels.router import ChannelRouter


def _make_router(orchestrator=None, db_pool=None, adapters=None, approval_channels=None):
    orc = orchestrator or _make_orchestrator()
    return ChannelRouter(
        adapters=adapters or [],
        orchestrator=orc,
        approval_manager=None,
        db_pool=db_pool,
        approval_channels=list(approval_channels or {"telegram", "web"}),
    )


def _make_orchestrator(response_text: str = "missão iniciada") -> AsyncMock:
    orc = AsyncMock()
    orc.route = AsyncMock(
        return_value=MagicMock(final_text=response_text, approval_request=None)
    )
    return orc


def _make_adapter(name: str, user_id: str = "U1") -> MagicMock:
    adapter = AsyncMock()
    adapter.name = name
    adapter.is_authorized = AsyncMock(return_value=True)
    adapter.send = AsyncMock()
    return adapter


def _make_db_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = AsyncMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return pool, conn


# ── Discord ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discord_mission_dispatched_and_replied():
    """C4+C5: missão via discord → orchestrator.route() chamado, send() chamado de volta."""
    adapter = _make_adapter("discord")
    orc = _make_orchestrator("relatório pronto")
    router = _make_router(orchestrator=orc, adapters=[adapter])

    msg = IncomingMessage(
        channel="discord", user_id="U111", user_display="Alice", text="construir um relatório"
    )
    await router.handle(msg)

    orc.route.assert_called_once()
    task_arg = orc.route.call_args[0][0]
    assert "construir um relatório" in task_arg.content

    adapter.send.assert_called_once()
    sent_msg: OutgoingMessage = adapter.send.call_args[0][1]
    assert "relatório pronto" in sent_msg.text


@pytest.mark.asyncio
async def test_discord_mission_persisted_in_and_out(tmp_path):
    """C11: mensagens discord gravadas direction=in e direction=out em channel_messages."""
    adapter = _make_adapter("discord")
    pool, conn = _make_db_pool()
    router = _make_router(adapters=[adapter], db_pool=pool)

    msg = IncomingMessage(
        channel="discord", user_id="U111", user_display="Alice", text="nova missão"
    )
    await router.handle(msg)

    calls = conn.execute.call_args_list
    # args: (query, channel, direction, user_id, user_display, text, thread_id, mission_id, session_id)
    directions = [c[0][2] for c in calls]  # índice 2 = direction
    assert "in" in directions
    assert "out" in directions


# ── Slack ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_mission_dispatched_and_replied():
    """C4+C5: missão via slack → orchestrator.route() chamado, resposta enviada."""
    adapter = _make_adapter("slack")
    orc = _make_orchestrator("tarefa slack ok")
    router = _make_router(orchestrator=orc, adapters=[adapter])

    msg = IncomingMessage(
        channel="slack", user_id="U222", user_display="Bob", text="analisar dados"
    )
    await router.handle(msg)

    orc.route.assert_called_once()
    adapter.send.assert_called_once()
    sent_msg: OutgoingMessage = adapter.send.call_args[0][1]
    assert "tarefa slack ok" in sent_msg.text


@pytest.mark.asyncio
async def test_slack_mission_persisted(tmp_path):
    """C11: mensagens slack gravadas direction=in e direction=out."""
    adapter = _make_adapter("slack")
    pool, conn = _make_db_pool()
    router = _make_router(adapters=[adapter], db_pool=pool)

    msg = IncomingMessage(
        channel="slack", user_id="U222", user_display="Bob", text="missão slack"
    )
    await router.handle(msg)

    calls = conn.execute.call_args_list
    directions = [c[0][2] for c in calls]
    assert "in" in directions
    assert "out" in directions


# ── Email ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_mission_dispatched_and_replied():
    """C4+C5: missão via email → orchestrator.route() chamado, resposta enviada."""
    adapter = _make_adapter("email")
    orc = _make_orchestrator("resumo por email")
    router = _make_router(orchestrator=orc, adapters=[adapter])

    msg = IncomingMessage(
        channel="email",
        user_id="user@example.com",
        user_display="Carol",
        text="resumir relatório trimestral",
        thread_id="<msg-id-1@example.com>",
    )
    await router.handle(msg)

    orc.route.assert_called_once()
    adapter.send.assert_called_once()
    sent_msg: OutgoingMessage = adapter.send.call_args[0][1]
    assert "resumo por email" in sent_msg.text


@pytest.mark.asyncio
async def test_email_mission_persisted():
    """C11: mensagens email gravadas direction=in e direction=out."""
    adapter = _make_adapter("email")
    pool, conn = _make_db_pool()
    router = _make_router(adapters=[adapter], db_pool=pool)

    msg = IncomingMessage(
        channel="email",
        user_id="user@example.com",
        user_display="Carol",
        text="missão via email",
    )
    await router.handle(msg)

    calls = conn.execute.call_args_list
    directions = [c[0][2] for c in calls]
    assert "in" in directions
    assert "out" in directions


# ── Thread_id propagado ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thread_id_propagated_in_reply():
    """C7: thread_id da IncomingMessage é propagado para OutgoingMessage.thread_id."""
    adapter = _make_adapter("discord")
    router = _make_router(adapters=[adapter])

    msg = IncomingMessage(
        channel="discord",
        user_id="U333",
        user_display="Dave",
        text="responder na thread",
        thread_id="thread-42",
    )
    await router.handle(msg)

    sent_msg: OutgoingMessage = adapter.send.call_args[0][1]
    assert sent_msg.thread_id == "thread-42"


# ── Session ID ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_id_format_is_channel_colon_user():
    """C2 helper: session_id gravado como {channel}:{user_id}."""
    adapter = _make_adapter("discord")
    pool, conn = _make_db_pool()
    router = _make_router(adapters=[adapter], db_pool=pool)

    msg = IncomingMessage(
        channel="discord", user_id="U444", user_display="Eve", text="olá"
    )
    await router.handle(msg)

    all_args = [call[0] for call in conn.execute.call_args_list]
    # args: (query, channel, direction, user_id, user_display, text, thread_id, mission_id, session_id)
    session_ids = [args[8] for args in all_args if len(args) > 8]
    assert len(session_ids) > 0
    assert all(sid == "discord:U444" for sid in session_ids)


# ── Unauthorized user bloqueado ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_user_not_dispatched():
    """C2: usuário não autorizado não chega ao orchestrator."""
    adapter = _make_adapter("discord")
    adapter.is_authorized = AsyncMock(return_value=False)
    orc = _make_orchestrator()
    router = _make_router(orchestrator=orc, adapters=[adapter])

    msg = IncomingMessage(
        channel="discord", user_id="EVIL", user_display="Hacker", text="missão maliciosa"
    )
    await router.handle(msg)

    orc.route.assert_not_called()
