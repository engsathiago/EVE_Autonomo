"""WebSocket multiplexado por tópico (F11 §5.3).

Único endpoint: WS /api/v1/stream?token=...
Heartbeat: ping a cada 20s, fecha se 3 pings sem pong.
Backpressure: >100 mensagens enfileiradas → desconecta.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from agent.observability.logger import get_logger
from agent.web.auth import verify_token
from agent.web import metrics as web_metrics

log = get_logger(__name__)

_HEARTBEAT_INTERVAL_S = 20
_MAX_MISSED_PINGS = 3
_MAX_QUEUE_SIZE = 100


class _WsSession:
    def __init__(self, ws: WebSocket, session_id: str) -> None:
        self.ws = ws
        self.session_id = session_id
        self.subscriptions: set[str] = set()
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._missed_pings = 0
        self._closed = False

    async def send(self, msg: dict) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            log.warning("web.ws.backpressure", session_id=self.session_id)
            await self.close()

    async def close(self) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass  # _send_loop vai encerrar via exceção ao tentar enviar no socket fechado
        except Exception:
            pass


# Registry global de sessões ativas
_sessions: dict[str, "_WsSession"] = {}


async def broadcast(topic: str, msg_type: str, data: Any) -> None:
    """Envia mensagem para todos os clientes assinando o tópico."""
    msg = {"topic": topic, "type": msg_type, "data": data}
    dead = []
    for sid, sess in list(_sessions.items()):
        if topic in sess.subscriptions:
            await sess.send(msg)
            web_metrics.ws_messages_total.labels(topic=topic, direction="out").inc()
    for sid in dead:
        _sessions.pop(sid, None)


def make_ws_router(
    get_orchestrator=None,
    get_task_store=None,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/api/v1/stream")
    async def ws_stream(ws: WebSocket, token: str = Query(default="")) -> None:
        if not verify_token(token):
            # Aceita antes de fechar — protocolo WS exige upgrade HTTP primeiro
            await ws.accept()
            await ws.close(code=4001, reason="Token inválido")
            return

        await ws.accept()
        import uuid as _uuid
        session_id = str(_uuid.uuid4())
        session = _WsSession(ws, session_id)
        _sessions[session_id] = session
        web_metrics.ws_connections_active.inc()

        log.info("web.ws.connected", session_id=session_id)

        try:
            await asyncio.gather(
                _recv_loop(session, get_orchestrator, get_task_store),
                _send_loop(session),
                _heartbeat_loop(session),
            )
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("web.ws.error", session_id=session_id, error=str(exc))
        finally:
            session._closed = True
            _sessions.pop(session_id, None)
            web_metrics.ws_connections_active.dec()
            log.info("web.ws.disconnected", session_id=session_id)

    return router


async def _recv_loop(
    session: "_WsSession",
    get_orchestrator=None,
    get_task_store=None,
) -> None:
    ws = session.ws
    while not session._closed:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=_HEARTBEAT_INTERVAL_S * 2)
        except asyncio.TimeoutError:
            continue
        except WebSocketDisconnect:
            break

        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        op = msg.get("op", "")

        if op == "pong":
            session._missed_pings = 0

        elif op == "subscribe":
            topic = msg.get("topic", "")
            if topic:
                session.subscriptions.add(topic)
                web_metrics.ws_messages_total.labels(topic=topic, direction="in").inc()

        elif op == "unsubscribe":
            topic = msg.get("topic", "")
            session.subscriptions.discard(topic)

        elif op == "chat.send":
            text = msg.get("text", "").strip()
            if not text:
                continue
            web_metrics.chat_messages_total.inc()
            asyncio.create_task(
                _handle_chat(session, text, get_orchestrator, get_task_store)
            )

        else:
            log.debug("web.ws.unknown_op", op=op, session_id=session.session_id)


async def _send_loop(session: "_WsSession") -> None:
    ws = session.ws
    while True:
        msg = await session._queue.get()
        if msg is None:
            break
        if ws.client_state == WebSocketState.DISCONNECTED:
            break
        try:
            await ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))
        except Exception as exc:
            log.warning("web.ws.send_error", error=str(exc))
            break


async def _heartbeat_loop(session: "_WsSession") -> None:
    ws = session.ws
    while not session._closed:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        if ws.client_state == WebSocketState.DISCONNECTED:
            break
        try:
            await ws.send_text(json.dumps({"op": "ping"}))
            session._missed_pings += 1
            if session._missed_pings >= _MAX_MISSED_PINGS:
                log.info("web.ws.zombie_killed", session_id=session.session_id)
                await session.close()
                break
        except Exception:
            break


async def _handle_chat(
    session: "_WsSession",
    text: str,
    get_orchestrator=None,
    get_task_store=None,
) -> None:
    from agent.web import metrics as web_metrics
    t0 = time.monotonic()

    orchestrator = get_orchestrator() if get_orchestrator else None
    task_store = get_task_store() if get_task_store else None

    if orchestrator is None or task_store is None:
        await session.send({"topic": "chat", "type": "error", "data": "Orchestrator indisponível"})
        return

    from agent.web.adapters.orchestrator import send_message
    try:
        async for event in send_message(orchestrator, task_store, text):
            await session.send({"topic": "chat", **event})
            web_metrics.ws_messages_total.labels(topic="chat", direction="out").inc()
    except Exception as exc:
        await session.send({"topic": "chat", "type": "error", "data": str(exc)})
    finally:
        latency = time.monotonic() - t0
        web_metrics.chat_response_latency_seconds.observe(latency)
