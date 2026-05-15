"""C5: WebSocket multiplexado — 2 tópicos simultâneos numa conexão."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


def test_ws_requires_valid_token() -> None:
    """WS com token inválido deve ser rejeitado (código 4001)."""
    with patch("agent.web.auth.verify_token", return_value=False):
        app = make_web_app()
        client = TestClient(app)
        with client.websocket_connect("/api/v1/stream?token=bad-token") as ws:
            # Starlette 1.x: receive() retorna dict com tipo websocket.close
            data = ws.receive()
            assert data.get("type") == "websocket.close"
            assert data.get("code") == 4001


def test_ws_subscribe_two_topics() -> None:
    """C5: Assina chat e traces no mesmo WS."""
    with patch("agent.web.auth.verify_token", return_value=True):
        app = make_web_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/stream?token=valid") as ws:
            ws.send_text(json.dumps({"op": "subscribe", "topic": "chat"}))
            ws.send_text(json.dumps({"op": "subscribe", "topic": "traces"}))
            ws.send_text(json.dumps({"op": "pong"}))
            # Conexão ainda ativa — fecha ao sair do context manager


def test_ws_unsubscribe() -> None:
    """Unsubscribe não deve derrubar a conexão."""
    with patch("agent.web.auth.verify_token", return_value=True):
        app = make_web_app()
        client = TestClient(app)

        with client.websocket_connect("/api/v1/stream?token=valid") as ws:
            ws.send_text(json.dumps({"op": "subscribe", "topic": "health"}))
            ws.send_text(json.dumps({"op": "unsubscribe", "topic": "health"}))
            ws.send_text(json.dumps({"op": "pong"}))
