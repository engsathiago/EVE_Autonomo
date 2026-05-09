from __future__ import annotations

import json
import uuid

from agent.channels.base import Channel, OutboundMessage
from agent.observability.logger import get_logger

log = get_logger(__name__)


class OutboundDispatcher:
    """Publica mensagens de saída no Redis para o gateway consumir."""

    def __init__(self, redis_client: "redis.asyncio.Redis") -> None:  # type: ignore[name-defined]
        self._redis = redis_client

    async def send(self, message: OutboundMessage) -> None:
        if message.idempotency_key is None:
            message = message.model_copy(update={"idempotency_key": str(uuid.uuid4())})

        queue_key = f"outbound:{message.channel.value}"
        payload = message.model_dump_json()

        await self._redis.lpush(queue_key, payload)
        log.info(
            "dispatcher.sent",
            channel=message.channel.value,
            chat_id=message.chat_id,
            key=message.idempotency_key,
        )

    async def send_telegram(
        self,
        chat_id: str,
        text: str,
        session_id: str | None = None,
        buttons: list[dict] | None = None,
    ) -> None:
        await self.send(
            OutboundMessage(
                session_id=session_id,
                channel=Channel.telegram,
                chat_id=chat_id,
                text=text,
                buttons=buttons or [],
            )
        )
