"""Processor structlog para redação de tokens e segredos em logs (C10).

Adicionado em shared_processors do configure_logging() para garantir que
nenhum token de plataforma apareça em log, mesmo que passado acidentalmente
como kwarg de contexto.

Padrões redatados:
- xox[abp]-... (tokens Slack)
- Strings de 50+ chars alfanuméricos (tokens de API em geral: Discord, etc.)
"""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    re.compile(r"xox[abp]-[A-Za-z0-9\-]+"),   # Slack bot/user/app tokens (xoxb, xoxp, xoxa)
    re.compile(r"xapp-[A-Za-z0-9\-]+"),         # Slack Socket Mode app tokens (xapp-)
    re.compile(r"[A-Za-z0-9]{50,}"),            # qualquer string 50+ chars alfanuméricos
]

_REPLACEMENT = "***REDACTED***"


def redact_secrets(
    logger: Any,
    method: Any,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor: redige tokens nos valores do event_dict."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            for pattern in _PATTERNS:
                value = pattern.sub(_REPLACEMENT, value)
            event_dict[key] = value
    return event_dict
