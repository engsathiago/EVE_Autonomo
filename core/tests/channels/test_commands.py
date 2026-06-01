"""Testes dos comandos de canal — transversal a todos os canais."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.channels.base import IncomingMessage


def _msg(text: str, channel: str = "discord") -> IncomingMessage:
    return IncomingMessage(channel=channel, user_id="U1", user_display="U", text=text)


async def _dispatch(text: str, orchestrator=None, approval_manager=None, approval_channels=None):
    from agent.channels.commands import dispatch_command
    return await dispatch_command(
        text=text,
        msg=_msg(text),
        session_id="discord:U1",
        orchestrator=orchestrator,
        approval_manager=approval_manager,
        approval_channels=approval_channels or {"telegram", "web"},
        db_pool=None,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_lists_all_commands():
    result = await _dispatch("/help")
    for cmd in ["/help", "/status", "/mission", "/missions", "/skills", "/approve", "/deny"]:
        assert cmd in result


# ── /status ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_without_orchestrator():
    result = await _dispatch("/status", orchestrator=None)
    assert "online" in result.lower()


@pytest.mark.asyncio
async def test_status_with_orchestrator():
    orc = MagicMock()
    result = await _dispatch("/status", orchestrator=orc)
    assert "online" in result.lower()


# ── /mission ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mission_without_text_returns_usage():
    result = await _dispatch("/mission")
    assert "uso" in result.lower() or "objetivo" in result.lower()


@pytest.mark.asyncio
async def test_mission_without_orchestrator():
    result = await _dispatch("/mission construir um relatório", orchestrator=None)
    assert "indisponível" in result.lower()


@pytest.mark.asyncio
async def test_mission_dispatches_to_orchestrator():
    """C4: /mission deve chamar orchestrator.route() com o texto da missão."""
    captured = []

    class FakeOrchestrator:
        async def route(self, task):
            captured.append(task)
            return MagicMock(final_text="missão iniciada")

    result = await _dispatch("/mission construir relatório", orchestrator=FakeOrchestrator())

    assert len(captured) == 1
    assert "construir relatório" in captured[0].content
    assert "missão iniciada" in result


# ── /missions ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missions_returns_info():
    result = await _dispatch("/missions")
    assert result  # não vazio


# ── /skills ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skills_returns_info():
    result = await _dispatch("/skills")
    assert result


# ── /cancel ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_without_id_returns_usage():
    result = await _dispatch("/cancel")
    assert "uso" in result.lower() or "id" in result.lower()


@pytest.mark.asyncio
async def test_cancel_with_id_returns_confirmation():
    result = await _dispatch("/cancel mission-123")
    assert "mission-123" in result


# ── Case-insensitive ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commands_are_case_insensitive():
    """Comandos em maiúsculas também funcionam."""
    result = await _dispatch("/HELP")
    assert "/mission" in result  # /help lista /mission
