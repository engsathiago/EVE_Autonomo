"""
Logging estruturado JSON para deploy (F10).

Configura:
  1. RotatingFileHandler com gzip nos arquivos antigos.
  2. Formatter JSON com campos obrigatórios (ts, level, component, msg).
  3. Filtro de redaction para secrets no nível do formatter.

Uso:
    from agent.deploy.logging import configure_deploy_logging
    configure_deploy_logging(log_dir="/var/lib/agent/logs")
"""
from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

# ── Padrões de redaction ──────────────────────────────────────────────────────

_REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'sk-[A-Za-z0-9\-_]{20,}'), "sk-***REDACTED***"),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-_.~+/]+=*'), "Bearer ***REDACTED***"),
    (re.compile(r'password\s*=\s*\S+', re.IGNORECASE), "password=***REDACTED***"),
    # Telegram bot token: {9,10 dígitos}:{35 chars base64url}
    (re.compile(r'\d{9,10}:[A-Za-z0-9_-]{35}'), "***BOT_TOKEN***"),
]


def _redact(text: str) -> str:
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ── JSON Formatter ────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Formata cada LogRecord como uma linha JSON com campos padronizados."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(record.created)
            ),
            "level": record.levelname,
            "component": record.name,
            "msg": record.getMessage(),
        }

        # Campos extras (structlog injeta via extra dict)
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName", "exc_info",
                "exc_text", "message", "taskName",
            ):
                entry[key] = value

        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)

        raw = json.dumps(entry, ensure_ascii=False, default=str)
        return _redact(raw)


# ── RotatingFileHandler com gzip ──────────────────────────────────────────────

class _GzipRotatingHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler que gzipa arquivos rotacionados."""

    def doRollover(self) -> None:
        super().doRollover()
        # O arquivo recém-rotacionado é self.baseFilename + ".1"
        rotated = self.baseFilename + ".1"
        if os.path.exists(rotated):
            gzipped = rotated + ".gz"
            with open(rotated, "rb") as f_in, gzip.open(gzipped, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.remove(rotated)
            # Renomeia .1.gz → .1.gz, .2.gz → .2.gz etc já tratados pelo super()


# ── Configuração pública ──────────────────────────────────────────────────────

def configure_deploy_logging(
    log_dir: str | None = None,
    log_level: str | None = None,
    rotate_size_mb: int | None = None,
    retain_files: int | None = None,
) -> None:
    """Adiciona file handler JSON rotacionado ao root logger.

    Chame depois de configure_logging() do observability existente.
    Não substitui o stdout handler — o systemd captura stdout automaticamente.
    """
    _dir = Path(log_dir or os.environ.get("AGENT_LOG_DIR", "/var/lib/agent/logs"))
    _level_str = (log_level or os.environ.get("AGENT_LOG_LEVEL", "INFO")).upper()
    _level = getattr(logging, _level_str, logging.INFO)
    _size_mb = rotate_size_mb or int(os.environ.get("AGENT_LOG_ROTATE_SIZE_MB", "100"))
    _retain = retain_files or int(os.environ.get("AGENT_LOG_RETAIN_FILES", "14"))

    try:
        _dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fora de ambiente de produção (sem /var/lib/agent) — silencia
        return

    handler = _GzipRotatingHandler(
        filename=str(_dir / "agent.log"),
        maxBytes=_size_mb * 1024 * 1024,
        backupCount=_retain,
        encoding="utf-8",
    )
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(_level)

    root = logging.getLogger()
    # Evita handlers duplicados em reload
    if not any(isinstance(h, _GzipRotatingHandler) for h in root.handlers):
        root.addHandler(handler)
