"""Testes do deploy logging: redaction e formatter JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agent.deploy.logging import _JsonFormatter, _redact


# ── Redaction ─────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_sk_key(self) -> None:
        result = _redact("key=sk-ant-api03-ABCDEFGHIJKLMNOPQRST1234567890AB")
        assert "sk-ant" not in result
        assert "REDACTED" in result

    def test_bearer_token(self) -> None:
        result = _redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGci" not in result
        assert "REDACTED" in result

    def test_password_field(self) -> None:
        result = _redact("password=mysecret123")
        assert "mysecret123" not in result
        assert "REDACTED" in result

    def test_telegram_bot_token(self) -> None:
        result = _redact("bot1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi" not in result
        assert "BOT_TOKEN" in result

    def test_safe_text_unchanged(self) -> None:
        safe = "user logged in from 192.168.1.1"
        assert _redact(safe) == safe

    def test_multiple_secrets_in_one_line(self) -> None:
        line = "key=sk-ant-ABCDEFGHIJKLMNOPQRST1234567 Bearer eyJtoken"
        result = _redact(line)
        assert "sk-ant-ABCDEFGHIJKLMNOPQRST1234567" not in result
        assert "eyJtoken" not in result


# ── JsonFormatter ─────────────────────────────────────────────────────────────

class TestJsonFormatter:
    def _make_record(self, msg: str, level: str = "INFO") -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.component",
            level=getattr(logging, level),
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        return record

    def test_output_is_valid_json(self) -> None:
        fmt = _JsonFormatter()
        record = self._make_record("hello world")
        result = fmt.format(record)
        parsed = json.loads(result)
        assert parsed["msg"] == "hello world"

    def test_required_fields_present(self) -> None:
        fmt = _JsonFormatter()
        record = self._make_record("test")
        parsed = json.loads(fmt.format(record))
        assert "ts" in parsed
        assert "level" in parsed
        assert "component" in parsed
        assert "msg" in parsed

    def test_level_uppercase(self) -> None:
        fmt = _JsonFormatter()
        record = self._make_record("test", "WARNING")
        parsed = json.loads(fmt.format(record))
        assert parsed["level"] == "WARNING"

    def test_secrets_redacted_in_output(self) -> None:
        fmt = _JsonFormatter()
        record = self._make_record("key=sk-ant-ABCDEFGHIJKLMNOPQRST1234567890AB found")
        result = fmt.format(record)
        assert "sk-ant-ABCDEFGHIJKLMNOPQRST1234567890AB" not in result

    def test_component_is_logger_name(self) -> None:
        fmt = _JsonFormatter()
        record = self._make_record("test")
        record.name = "agent.deploy.supervisor"
        parsed = json.loads(fmt.format(record))
        assert parsed["component"] == "agent.deploy.supervisor"


# ── configure_deploy_logging ───────────────────────────────────────────────────

class TestConfigureDeployLogging:
    def test_no_error_without_writable_dir(self, tmp_path: Path) -> None:
        """Não deve levantar exceção se o dir não existe."""
        from agent.deploy.logging import configure_deploy_logging
        # Dir acessível
        configure_deploy_logging(log_dir=str(tmp_path / "logs"))

    def test_adds_handler_to_root_logger(self, tmp_path: Path) -> None:
        from agent.deploy.logging import configure_deploy_logging, _GzipRotatingHandler
        configure_deploy_logging(log_dir=str(tmp_path / "logs2"))
        root = logging.getLogger()
        has_handler = any(isinstance(h, _GzipRotatingHandler) for h in root.handlers)
        assert has_handler
        # Limpa para não poluir outros testes
        root.handlers = [h for h in root.handlers if not isinstance(h, _GzipRotatingHandler)]

    def test_no_duplicate_handlers(self, tmp_path: Path) -> None:
        from agent.deploy.logging import configure_deploy_logging, _GzipRotatingHandler
        log_dir = str(tmp_path / "logs3")
        configure_deploy_logging(log_dir=log_dir)
        configure_deploy_logging(log_dir=log_dir)
        root = logging.getLogger()
        count = sum(1 for h in root.handlers if isinstance(h, _GzipRotatingHandler))
        assert count == 1
        root.handlers = [h for h in root.handlers if not isinstance(h, _GzipRotatingHandler)]
