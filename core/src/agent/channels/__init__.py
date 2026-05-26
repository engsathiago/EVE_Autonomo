from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from agent.channels.base import (
    Channel,
    ChannelAdapter,
    ConfigError,
    InboundMessage,
    IncomingMessage,
    OutboundMessage,
    OutgoingMessage,
)
from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager

log = get_logger(__name__)

__all__ = [
    "Channel",
    "ChannelAdapter",
    "ConfigError",
    "InboundMessage",
    "IncomingMessage",
    "OutboundMessage",
    "OutgoingMessage",
    "bootstrap_channels",
    "get_channel_statuses",
]

# Estado global dos adapters ativos (populado por bootstrap_channels)
_active_adapters: list[ChannelAdapter] = []
_channel_statuses: dict[str, str] = {}  # channel_name → "up" | "disabled" | "down:reason"


async def bootstrap_channels(
    orchestrator: Any | None = None,
    approval_manager: ApprovalManager | None = None,
    db_pool: Any = None,
) -> list[ChannelAdapter]:
    """Inicializa os adapters habilitados em CHANNELS_ENABLED.

    Para cada canal habilitado:
    - Lê as variáveis de ambiente necessárias.
    - Se faltar token ou allowlist, loga WARN e pula (não levanta).
    - Conecta ao ChannelRouter.
    - Chama adapter.start().

    Retorna a lista de adapters iniciados.
    """
    global _active_adapters, _channel_statuses

    from agent.channels.router import ChannelRouter

    enabled_raw = os.getenv("CHANNELS_ENABLED", "")
    enabled = [c.strip() for c in enabled_raw.split(",") if c.strip()]

    if not enabled:
        log.info("channels.bootstrap.none_enabled")
        return []

    adapters: list[ChannelAdapter] = []

    # Instancia adapters primeiro (sem router ainda)
    for channel_name in enabled:
        try:
            adapter = _create_adapter(channel_name)
            adapters.append(adapter)
            log.info("channels.bootstrap.created", channel=channel_name)
        except ConfigError as exc:
            log.warning("channels.bootstrap.disabled", channel=channel_name, reason=str(exc))
            _channel_statuses[channel_name] = f"disabled:{exc}"
        except Exception as exc:
            log.error("channels.bootstrap.error", channel=channel_name, error=str(exc))
            _channel_statuses[channel_name] = f"error:{exc}"

    if not adapters:
        return []

    # Cria router com todos os adapters
    rate_user = int(os.getenv("RATE_LIMIT_PER_USER_PER_MIN", "20"))
    rate_channel = int(os.getenv("RATE_LIMIT_PER_CHANNEL_PER_MIN", "120"))
    approval_channels_raw = os.getenv("APPROVAL_CHANNELS", "telegram,web")
    approval_channels = [c.strip() for c in approval_channels_raw.split(",") if c.strip()]

    router = ChannelRouter(
        adapters=adapters,
        orchestrator=orchestrator,
        approval_manager=approval_manager,
        db_pool=db_pool,
        rate_limit_user_per_min=rate_user,
        rate_limit_channel_per_min=rate_channel,
        approval_channels=approval_channels,
    )

    # Injeta router em cada adapter e inicia
    started: list[ChannelAdapter] = []
    for adapter in adapters:
        if hasattr(adapter, "set_router"):
            adapter.set_router(router)
        try:
            await adapter.start()
            _channel_statuses[adapter.name] = "up"
            started.append(adapter)
            log.info("channels.bootstrap.started", channel=adapter.name)
        except Exception as exc:
            log.error("channels.bootstrap.start_failed", channel=adapter.name, error=str(exc))
            _channel_statuses[adapter.name] = f"down:{exc}"

    _active_adapters = started
    return started


async def stop_channels() -> None:
    """Para todos os adapters ativos. Chamado no shutdown."""
    for adapter in _active_adapters:
        try:
            await adapter.stop()
            _channel_statuses[adapter.name] = "stopped"
        except Exception as exc:
            log.warning("channels.stop_failed", channel=adapter.name, error=str(exc))
    _active_adapters.clear()


def get_channel_statuses() -> dict[str, str]:
    """Retorna sub-status por canal para o /health endpoint."""
    return dict(_channel_statuses)


def _create_adapter(channel_name: str) -> ChannelAdapter:
    """Factory: cria o adapter correto para o canal dado."""
    if channel_name == "discord":
        from agent.channels.discord_adapter import DiscordAdapter

        return DiscordAdapter.from_env()

    if channel_name == "slack":
        from agent.channels.slack_adapter import SlackAdapter

        return SlackAdapter.from_env()

    if channel_name == "email":
        from agent.channels.email_adapter import EmailAdapter

        return EmailAdapter.from_env()

    raise ConfigError(
        f"Canal desconhecido: '{channel_name}'. Valores válidos: discord, slack, email"
    )
