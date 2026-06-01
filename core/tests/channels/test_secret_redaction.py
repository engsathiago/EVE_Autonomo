"""TDD — Tokens nunca aparecem em logs (C10).

Testa o processor structlog de redação de segredos.
"""

from __future__ import annotations

from agent.channels.redaction import redact_secrets


def _call(event_dict: dict) -> dict:
    """Chama o processor como se fosse o structlog."""
    return redact_secrets(None, None, dict(event_dict))


def test_xoxb_token_is_redacted():
    """Token xoxb- (Slack bot) deve ser redatado."""
    result = _call({"token": "xoxb-abc123-xyz789-1234567890abcdef"})
    assert "xoxb" not in result["token"]
    assert "REDACTED" in result["token"]


def test_xapp_token_is_redacted():
    """Token xapp- (Slack app) deve ser redatado."""
    result = _call({"token": "xapp-1-A1234-5678-abcdefghijklmnopqrst"})
    assert "xapp" not in result["token"]
    assert "REDACTED" in result["token"]


def test_xoxp_token_is_redacted():
    """Token xoxp- (Slack user) deve ser redatado."""
    result = _call({"token": "xoxp-111-222-333-abcdef1234567890"})
    assert "xoxp" not in result["token"]


def test_long_alphanum_string_is_redacted():
    """String de 50+ chars alfanuméricos (token-like) deve ser redatada."""
    long_token = "A" * 55
    result = _call({"key": long_token})
    assert long_token not in result["key"]
    assert "REDACTED" in result["key"]


def test_short_string_is_not_redacted():
    """Strings curtas normais não são redatadas."""
    result = _call({"user": "alice"})
    assert result["user"] == "alice"


def test_regular_text_not_redacted():
    """Texto regular de log não é modificado."""
    result = _call({"event": "canal iniciado", "channel": "discord"})
    assert result["event"] == "canal iniciado"
    assert result["channel"] == "discord"


def test_non_string_values_are_untouched():
    """Valores não-string (int, None, dict) não são alterados."""
    result = _call({"count": 42, "data": None, "nested": {"x": 1}})
    assert result["count"] == 42
    assert result["data"] is None


def test_multiple_tokens_in_same_field_all_redacted():
    """Múltiplos tokens no mesmo campo são todos redatados."""
    result = _call({"msg": "tokens: xoxb-abc1-def2-ghi3 e xapp-X-Y-Z"})
    assert "xoxb" not in result["msg"]
    assert "xapp" not in result["msg"]


def test_long_alphanumeric_token_is_redacted():
    """Qualquer token de 50+ chars alfanuméricos contíguos é redatado."""
    # Ex: token de API gerado aleatoriamente (Discord, OpenAI, etc.)
    api_token = "abcdefghij0123456789ABCDEFGHIJ0123456789abcdefghij"  # 50 chars
    assert len(api_token) == 50
    result = _call({"API_KEY": api_token})
    assert api_token not in result["API_KEY"]
    assert "REDACTED" in result["API_KEY"]
