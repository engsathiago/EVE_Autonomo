"""Middleware de autenticação por token para o Web UI (F11).

Token armazenado em ~/.agent/web_token (chmod 600).
Comparação via hmac.compare_digest para evitar timing attacks.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

from agent.observability.logger import get_logger

log = get_logger(__name__)

_TOKEN_FILE = Path(os.getenv("AGENT_WEB_TOKEN_FILE", str(Path.home() / ".agent" / "web_token")))

# Cache in-memory do hash do token + timestamp de invalidação
_token_hash: str | None = None
_token_loaded_at: float = 0.0
_TOKEN_CACHE_TTL_S = 5.0  # invalida cache em até 5s (C9)


def _load_token_hash() -> str | None:
    """Lê token do disco e retorna hash sha256. Cacheia por 5s."""
    global _token_hash, _token_loaded_at

    now = time.monotonic()
    if _token_hash is not None and (now - _token_loaded_at) < _TOKEN_CACHE_TTL_S:
        return _token_hash

    try:
        raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        _token_hash = hashlib.sha256(raw.encode()).hexdigest()
        _token_loaded_at = now
        return _token_hash
    except FileNotFoundError:
        _token_hash = None
        return None
    except Exception as exc:
        log.warning("web.auth.token_read_error", error=str(exc))
        return None


def invalidate_token_cache() -> None:
    """Força releitura na próxima request (chamado após token-rotate)."""
    global _token_hash, _token_loaded_at
    _token_hash = None
    _token_loaded_at = 0.0


def verify_token(token: str) -> bool:
    """Retorna True se o token bater com o hash armazenado."""
    stored_hash = _load_token_hash()
    if stored_hash is None:
        return False
    candidate_hash = hashlib.sha256(token.encode()).hexdigest()
    return hmac.compare_digest(stored_hash, candidate_hash)


async def require_token(request: Request) -> None:
    """Dependency FastAPI — lança 401 se token ausente ou inválido."""
    token = request.headers.get("X-Agent-Token") or request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="X-Agent-Token ausente")
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Token inválido")


def generate_token() -> str:
    """Gera token seguro de 32 bytes base64url."""
    return secrets.token_urlsafe(32)


def write_token(token: str) -> None:
    """Escreve token no arquivo e ajusta permissões para 600."""
    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    _TOKEN_FILE.chmod(0o600)
    invalidate_token_cache()


def read_token() -> str | None:
    """Lê o token atual do arquivo (sem caching)."""
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
