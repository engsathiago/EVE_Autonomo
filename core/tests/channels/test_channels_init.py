"""Testes para channels/__init__.py: bootstrap_channels, stop_channels, get_channel_statuses."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.channels.base import ConfigError

# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_module():
    """Limpa estado global do módulo channels antes de cada teste."""
    import agent.channels as ch
    ch._active_adapters.clear()
    ch._channel_statuses.clear()


def _make_adapter(name: str) -> AsyncMock:
    a = AsyncMock()
    a.name = name
    a.start = AsyncMock()
    a.stop = AsyncMock()
    a.set_router = MagicMock()
    return a


# ── bootstrap sem canais habilitados ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_no_channels_returns_empty():
    _reset_module()
    with patch.dict(os.environ, {"CHANNELS_ENABLED": ""}, clear=False):
        from agent.channels import bootstrap_channels
        result = await bootstrap_channels()
    assert result == []


@pytest.mark.asyncio
async def test_bootstrap_channels_disabled_env_not_set():
    _reset_module()
    env = {k: v for k, v in os.environ.items() if k != "CHANNELS_ENABLED"}
    with patch.dict(os.environ, env, clear=True):
        from agent.channels import bootstrap_channels
        result = await bootstrap_channels()
    assert result == []


# ── bootstrap com adapter que levanta ConfigError ─────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_config_error_sets_disabled_status():
    _reset_module()
    with patch.dict(os.environ, {"CHANNELS_ENABLED": "discord"}, clear=False):
        with patch("agent.channels._create_adapter", side_effect=ConfigError("token ausente")):
            from agent.channels import bootstrap_channels
            result = await bootstrap_channels()

    assert result == []
    from agent.channels import get_channel_statuses
    statuses = get_channel_statuses()
    assert "discord" in statuses
    assert "disabled" in statuses["discord"]


@pytest.mark.asyncio
async def test_bootstrap_generic_error_sets_error_status():
    _reset_module()
    with patch.dict(os.environ, {"CHANNELS_ENABLED": "slack"}, clear=False):
        with patch("agent.channels._create_adapter", side_effect=RuntimeError("falha")):
            from agent.channels import bootstrap_channels
            result = await bootstrap_channels()

    assert result == []
    from agent.channels import get_channel_statuses
    statuses = get_channel_statuses()
    assert "error" in statuses.get("slack", "")


# ── bootstrap com adapter funcionando ────────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_adapter_started_appears_in_statuses():
    _reset_module()
    adapter = _make_adapter("discord")

    with patch.dict(os.environ, {"CHANNELS_ENABLED": "discord", "APPROVAL_CHANNELS": "telegram,web"}, clear=False):
        with patch("agent.channels._create_adapter", return_value=adapter):
            with patch("agent.channels.router.ChannelRouter"):
                from agent.channels import bootstrap_channels
                result = await bootstrap_channels(orchestrator=None, db_pool=None)

    adapter.set_router.assert_called_once()
    adapter.start.assert_called_once()

    from agent.channels import get_channel_statuses
    statuses = get_channel_statuses()
    assert statuses.get("discord") == "up"
    assert len(result) == 1


@pytest.mark.asyncio
async def test_bootstrap_adapter_start_failure_sets_down_status():
    _reset_module()
    adapter = _make_adapter("email")
    adapter.start = AsyncMock(side_effect=Exception("imap falhou"))

    with patch.dict(os.environ, {"CHANNELS_ENABLED": "email", "APPROVAL_CHANNELS": "telegram,web"}, clear=False):
        with patch("agent.channels._create_adapter", return_value=adapter):
            with patch("agent.channels.router.ChannelRouter"):
                from agent.channels import bootstrap_channels
                result = await bootstrap_channels()

    assert result == []
    from agent.channels import get_channel_statuses
    statuses = get_channel_statuses()
    assert "down" in statuses.get("email", "")


# ── stop_channels ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_channels_calls_stop_on_all_adapters():
    import agent.channels as ch
    _reset_module()
    a1 = _make_adapter("discord")
    a2 = _make_adapter("slack")
    ch._active_adapters.extend([a1, a2])
    ch._channel_statuses.update({"discord": "up", "slack": "up"})

    from agent.channels import stop_channels
    await stop_channels()

    a1.stop.assert_called_once()
    a2.stop.assert_called_once()
    assert ch._active_adapters == []


@pytest.mark.asyncio
async def test_stop_channels_handles_stop_exception():
    import agent.channels as ch
    _reset_module()
    a1 = _make_adapter("email")
    a1.stop = AsyncMock(side_effect=Exception("stop falhou"))
    ch._active_adapters.append(a1)

    from agent.channels import stop_channels
    await stop_channels()  # não deve propagar exceção


# ── get_channel_statuses ──────────────────────────────────────────────────────

def test_get_channel_statuses_returns_copy():
    import agent.channels as ch
    _reset_module()
    ch._channel_statuses.update({"discord": "up", "slack": "disabled:sem token"})

    from agent.channels import get_channel_statuses
    statuses = get_channel_statuses()
    assert statuses == {"discord": "up", "slack": "disabled:sem token"}

    # Garantir que é cópia (modificação não afeta módulo)
    statuses["discord"] = "down"
    assert ch._channel_statuses["discord"] == "up"


# ── _create_adapter factory ───────────────────────────────────────────────────

def test_create_adapter_unknown_channel_raises_config_error():
    from agent.channels import _create_adapter
    with pytest.raises(ConfigError, match="Canal desconhecido"):
        _create_adapter("whatsapp")


def test_create_adapter_discord_calls_from_env():
    with patch("agent.channels.discord_adapter.DiscordAdapter.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        from agent.channels import _create_adapter
        _create_adapter("discord")
    mock_from_env.assert_called_once()


def test_create_adapter_slack_calls_from_env():
    with patch("agent.channels.slack_adapter.SlackAdapter.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        from agent.channels import _create_adapter
        _create_adapter("slack")
    mock_from_env.assert_called_once()


def test_create_adapter_email_calls_from_env():
    with patch("agent.channels.email_adapter.EmailAdapter.from_env") as mock_from_env:
        mock_from_env.return_value = MagicMock()
        from agent.channels import _create_adapter
        _create_adapter("email")
    mock_from_env.assert_called_once()
