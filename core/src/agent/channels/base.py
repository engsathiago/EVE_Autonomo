from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class Channel(str, Enum):
    telegram = "telegram"
    slack = "slack"
    discord = "discord"
    cli = "cli"


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
