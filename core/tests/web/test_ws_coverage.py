"""Testes diretos de cobertura do WS — _recv_loop, _send_loop, broadcast, _handle_chat."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from agent.web.routes.ws import (
    _WsSession,
    _sessions,
    _recv_loop,
    _send_loop,
    _handle_chat,
    broadcast,
)


@pytest.mark.asyncio
async def test_send_when_already_closed() -> None:
    """send() retorna imediatamente quando _closed=True — linha 39."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "closed-s")
    session._closed = True
    await session.send({"data": "ignored"})
    assert session._queue.empty()


@pytest.mark.asyncio
async def test_broadcast_enqueues_in_subscribed_session() -> None:
    """broadcast() coloca mensagem na fila da sessão inscrita — linhas 62-64."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "bc-s")
    session.subscriptions.add("chat")
    _sessions["bc-s"] = session
    try:
        await broadcast("chat", "token", {"text": "hi"})
        msg = session._queue.get_nowait()
        assert msg["topic"] == "chat"
        assert msg["type"] == "token"
    finally:
        _sessions.pop("bc-s", None)


@pytest.mark.asyncio
async def test_broadcast_skips_unsubscribed_session() -> None:
    """broadcast() não envia para sessões sem o tópico — linhas 61-64 (branch)."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "no-sub")
    _sessions["no-sub"] = session
    try:
        await broadcast("traces", "event", {})
        assert session._queue.empty()
    finally:
        _sessions.pop("no-sub", None)


@pytest.mark.asyncio
async def test_recv_loop_subscribe_and_pong() -> None:
    """_recv_loop processa subscribe + pong — linhas 130-137."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-sub")
    session._missed_pings = 3

    msgs = [
        json.dumps({"op": "subscribe", "topic": "chat"}),
        json.dumps({"op": "pong"}),
    ]
    idx = 0

    async def fake_recv():
        nonlocal idx
        if idx < len(msgs):
            v = msgs[idx]
            idx += 1
            return v
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)
    assert "chat" in session.subscriptions
    assert session._missed_pings == 0


@pytest.mark.asyncio
async def test_recv_loop_unsubscribe() -> None:
    """_recv_loop processa unsubscribe — linhas 139-140."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-unsub")
    session.subscriptions.add("health")

    idx = 0

    async def fake_recv():
        nonlocal idx
        idx += 1
        if idx == 1:
            return json.dumps({"op": "unsubscribe", "topic": "health"})
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)
    assert "health" not in session.subscriptions


@pytest.mark.asyncio
async def test_recv_loop_invalid_json_ignored() -> None:
    """_recv_loop ignora payloads inválidos — linhas 125-126 (JSONDecodeError)."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-json")
    idx = 0

    async def fake_recv():
        nonlocal idx
        idx += 1
        if idx == 1:
            return "not-json"
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)  # não deve lançar


@pytest.mark.asyncio
async def test_recv_loop_unknown_op_logged() -> None:
    """_recv_loop registra ops desconhecidas — else branch linha 153."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-unk")
    idx = 0

    async def fake_recv():
        nonlocal idx
        idx += 1
        if idx == 1:
            return json.dumps({"op": "mystery"})
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)  # não deve lançar


@pytest.mark.asyncio
async def test_recv_loop_timeout_continues() -> None:
    """_recv_loop continua após TimeoutError — linhas 119-121."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-timeout")
    call_n = 0

    async def fake_recv():
        nonlocal call_n
        call_n += 1
        if call_n == 1:
            raise asyncio.TimeoutError()
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)
    assert call_n == 2


@pytest.mark.asyncio
async def test_recv_loop_exits_when_closed() -> None:
    """_recv_loop sai quando _closed=True — while not session._closed."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-close")
    session._closed = True
    # Nunca deve chamar receive_text
    mock_ws.receive_text = AsyncMock(side_effect=AssertionError("não deve ser chamado"))
    await _recv_loop(session, None, None)


@pytest.mark.asyncio
async def test_send_loop_sends_and_stops_on_none() -> None:
    """_send_loop envia mensagens e para ao receber None — linhas 160-173."""
    mock_ws = AsyncMock()
    mock_ws.client_state = WebSocketState.CONNECTED
    session = _WsSession(mock_ws, "sl-send")

    session._queue.put_nowait({"msg": 1})
    session._queue.put_nowait({"msg": 2})
    session._queue.put_nowait(None)

    await _send_loop(session)
    assert mock_ws.send_text.call_count == 2


@pytest.mark.asyncio
async def test_send_loop_skips_on_disconnected_state() -> None:
    """_send_loop não envia quando WS está DISCONNECTED — linha 163."""
    mock_ws = AsyncMock()
    mock_ws.client_state = WebSocketState.DISCONNECTED
    session = _WsSession(mock_ws, "sl-disc")

    session._queue.put_nowait({"msg": 1})
    session._queue.put_nowait(None)

    await _send_loop(session)
    mock_ws.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_loop_exits_on_exception() -> None:
    """_send_loop para quando send_text levanta exceção — linhas 165-169."""
    mock_ws = AsyncMock()
    mock_ws.client_state = WebSocketState.CONNECTED
    mock_ws.send_text.side_effect = RuntimeError("conn lost")
    session = _WsSession(mock_ws, "sl-exc")

    session._queue.put_nowait({"msg": 1})
    await _send_loop(session)  # sai na exceção


@pytest.mark.asyncio
async def test_handle_chat_no_orchestrator_sends_error() -> None:
    """_handle_chat envia error quando orchestrator=None — linhas 201-203."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "hc-none")

    await _handle_chat(session, "hello", None, None)
    msg = session._queue.get_nowait()
    assert msg.get("type") == "error"


@pytest.mark.asyncio
async def test_handle_chat_no_task_store_sends_error() -> None:
    """_handle_chat envia error quando task_store=None."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "hc-no-ts")

    await _handle_chat(session, "hello", lambda: MagicMock(), None)
    msg = session._queue.get_nowait()
    assert msg.get("type") == "error"


@pytest.mark.asyncio
async def test_recv_loop_chat_send_with_no_orchestrator() -> None:
    """_recv_loop processa chat.send e lida com orchestrator=None."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-chat")
    idx = 0

    async def fake_recv():
        nonlocal idx
        idx += 1
        if idx == 1:
            return json.dumps({"op": "chat.send", "text": "olá"})
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    # Sem orchestrator — _handle_chat envia error na fila; nenhuma exceção deve escapar
    await _recv_loop(session, None, None)
    # Aguarda tasks criadas via create_task
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_recv_loop_chat_send_empty_text_ignored() -> None:
    """_recv_loop ignora chat.send com texto vazio — linha 151 continue."""
    mock_ws = MagicMock()
    session = _WsSession(mock_ws, "r-empty-chat")
    idx = 0

    async def fake_recv():
        nonlocal idx
        idx += 1
        if idx == 1:
            return json.dumps({"op": "chat.send", "text": ""})
        raise WebSocketDisconnect()

    mock_ws.receive_text = fake_recv
    await _recv_loop(session, None, None)
    # Fila vazia — texto vazio foi ignorado
    assert session._queue.empty()
