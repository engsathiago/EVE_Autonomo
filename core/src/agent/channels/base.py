from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class Channel(str, Enum):
    telegram = "telegram"
    slack = "slack"
    discord = "discord"
    cli = "cli"
    email = "email"
    web = "web"


class InboundMessage(BaseModel):
    session_id: str
    text: str
    channel: Channel
    user_id: str
    metadata: dict[str, Any] = {}


class OutboundMessage(BaseModel):
    session_id: str | None = None
    channel: Channel
    chat_id: str
    text: str
    buttons: list[dict[str, Any]] = []
    idempotency_key: str | None = None
    metadata: dict[str, Any] = {}


# ── F12: tipos e interface para adaptadores de canal extra ───────────────────

@dataclass
class IncomingMessage:
    """Mensagem recebida de qualquer canal (Discord, Slack, Email, etc.)."""
    channel: str
    user_id: str
    user_display: str
    text: str
    thread_id: Optional[str] = None
    raw: Optional[dict] = field(default=None)


@dataclass
class OutgoingMessage:
    """Mensagem a enviar de volta por um canal."""
    text: str
    thread_id: Optional[str] = None
    mission_id: Optional[str] = None
    is_approval: bool = False


class ChannelAdapter(ABC):
    """Interface comum para todos os adaptadores de canal (F12)."""

    name: str  # "discord" | "slack" | "email"

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, user_id: str, msg: OutgoingMessage) -> None: ...

    @abstractmethod
    async def is_authorized(self, user_id: str) -> bool: ...


class ConfigError(Exception):
    """Levantada quando um adapter não pode iniciar por falta de configuração."""
