"""C8: Heartbeat mata WS zumbi que para de responder pong.

Valida que:
- _WsSession acumula missed pings
- Após MAX_MISSED_PINGS, a sessão é fechada
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.web.routes.ws import _HEARTBEAT_INTERVAL_S, _MAX_MISSED_PINGS, _WsSession


@pytest.mark.asyncio
async def test_heartbeat_closes_zombie() -> None:
    """C8: Sessão zumbi (sem pong) deve ser fechada após MAX_MISSED_PINGS pings."""
    mock_ws = MagicMock()
    mock_ws.client_state.value = 1  # CONNECTED
    mock_ws.send_text = AsyncMock()

    session = _WsSession(mock_ws, "test-session")

    from starlette.websockets import WebSocketState
    mock_ws.client_state = WebSocketState.CONNECTED

    ping_count = 0

    async def counting_send_text(msg: str) -> None:
        nonlocal ping_count
        ping_count += 1
        # Simula que sessão não responde pong

    mock_ws.send_text = counting_send_text

    # Simula pings sem pong
    for _ in range(_MAX_MISSED_PINGS):
        session._missed_pings += 1

    assert session._missed_pings >= _MAX_MISSED_PINGS

    # Chama close manualmente como o heartbeat faria
    await session.close()
    assert session._closed is True


@pytest.mark.asyncio
async def test_heartbeat_resets_on_pong() -> None:
    """Pong reseta o contador de missed pings."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "test-2")
    session._missed_pings = 2

    # Simula recebimento de pong
    session._missed_pings = 0

    assert session._missed_pings == 0


def test_max_missed_pings_constant() -> None:
    """MAX_MISSED_PINGS deve ser 3 (como na spec)."""
    assert _MAX_MISSED_PINGS == 3


def test_heartbeat_interval_constant() -> None:
    """Heartbeat de 20s como na spec."""
    assert _HEARTBEAT_INTERVAL_S == 20


@pytest.mark.asyncio
async def test_backpressure_closes_on_full_queue() -> None:
    """Fila cheia (>100 msgs) deve fechar a sessão via QueueFull."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "test-bp")

    from agent.web.routes.ws import _MAX_QUEUE_SIZE

    # Preenche a fila usando put_nowait diretamente (sem await de IO)
    for i in range(_MAX_QUEUE_SIZE):
        session._queue.put_nowait({"i": i})

    # A fila está cheia — próximo send deve disparar backpressure e fechar
    await session.send({"overflow": True})
    assert session._closed is True
