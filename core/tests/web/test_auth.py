"""Testes de autenticação — C2 (sem token → 401) e C9 (token rotacionado invalida em <5s)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.web.server import make_web_app


@pytest.fixture()
def token_file(tmp_path: Path) -> Path:
    tf = tmp_path / "web_token"
    tf.write_text("test-token-abc123\n")
    tf.chmod(0o600)
    return tf


def test_no_token_returns_401(token_file: Path) -> None:
    """C2: requisição sem token deve retornar 401."""
    app = make_web_app()
    with patch("agent.web.auth._TOKEN_FILE", token_file):
        from agent.web import auth as _auth

        _auth._token_hash = None
        _auth._token_loaded_at = 0.0
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/system/info")
    assert resp.status_code == 401


def test_wrong_token_returns_401(token_file: Path) -> None:
    """C2: token errado deve retornar 401."""
    app = make_web_app()
    with patch("agent.web.auth._TOKEN_FILE", token_file):
        from agent.web import auth as _auth

        _auth._token_hash = None
        _auth._token_loaded_at = 0.0
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/system/info", headers={"X-Agent-Token": "wrong-token"})
    assert resp.status_code == 401


def test_valid_token_returns_200(token_file: Path) -> None:
    """C2: token correto deve retornar 200."""
    app = make_web_app()
    with patch("agent.web.auth._TOKEN_FILE", token_file):
        from agent.web import auth as _auth

        _auth._token_hash = None
        _auth._token_loaded_at = 0.0
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/system/info", headers={"X-Agent-Token": "test-token-abc123"})
    assert resp.status_code == 200


def test_token_rotation_invalidates_in_5s(tmp_path: Path) -> None:
    """C9: token rotacionado deve ser rejeitado em < cache TTL (5s)."""
    from agent.web import auth

    tf = tmp_path / "web_token"
    tf.write_text("old-token\n")
    tf.chmod(0o600)

    with patch("agent.web.auth._TOKEN_FILE", tf):
        auth._token_hash = None
        auth._token_loaded_at = 0.0
        assert auth.verify_token("old-token") is True

        # Rotaciona token
        auth.write_token("new-token")

        # Cache deve ser invalidado imediatamente após rotate
        assert auth.verify_token("old-token") is False
        assert auth.verify_token("new-token") is True


def test_missing_token_file_returns_false(tmp_path: Path) -> None:
    """Arquivo de token inexistente deve retornar False."""
    from agent.web import auth

    missing = tmp_path / "nonexistent"
    with patch("agent.web.auth._TOKEN_FILE", missing):
        auth._token_hash = None
        auth._token_loaded_at = 0.0
        assert auth.verify_token("anything") is False


def test_generate_token_is_32_bytes_b64() -> None:
    """Token gerado deve ter 32 bytes base64url (43 chars sem padding)."""
    from agent.web.auth import generate_token

    tok = generate_token()
    assert len(tok) >= 40
    import re

    assert re.match(r"^[A-Za-z0-9_-]+$", tok)
