"""TDD — Contrato do ChannelAdapter (C14).

Escrito ANTES da implementação para definir a interface pública.
"""
from __future__ import annotations

import pytest

from agent.channels.base import (
    ChannelAdapter,
    ConfigError,
    IncomingMessage,
    OutgoingMessage,
)


# ── Contrato ABC ──────────────────────────────────────────────────────────────

class _FullAdapter(ChannelAdapter):
    """Implementação completa — deve ser instanciável."""
    name = "test"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, user_id: str, msg: OutgoingMessage) -> None:
        pass

    async def is_authorized(self, user_id: str) -> bool:
        return True


class _PartialAdapter(ChannelAdapter):
    """Implementação incompleta (falta send e is_authorized)."""
    name = "partial"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def test_adapter_abc_not_instantiable_directly():
    """ChannelAdapter não pode ser instanciado diretamente."""
    with pytest.raises(TypeError):
        ChannelAdapter()  # type: ignore[abstract]


def test_adapter_partial_implementation_raises():
    """Implementação incompleta levanta TypeError na instanciação."""
    with pytest.raises(TypeError):
        _PartialAdapter()  # type: ignore[abstract]


def test_adapter_full_implementation_instantiable():
    """Implementação completa pode ser instanciada."""
    adapter = _FullAdapter()
    assert adapter.name == "test"


@pytest.mark.asyncio
async def test_adapter_full_methods_callable():
    """Métodos do adapter completo são chamáveis."""
    adapter = _FullAdapter()
    await adapter.start()
    await adapter.stop()
    msg = OutgoingMessage(text="oi")
    await adapter.send("123", msg)
    assert await adapter.is_authorized("123") is True


# ── IncomingMessage ───────────────────────────────────────────────────────────

def test_incoming_message_required_fields():
    """IncomingMessage requer channel, user_id, user_display e text."""
    msg = IncomingMessage(
        channel="discord",
        user_id="111",
        user_display="Alice",
        text="olá",
    )
    assert msg.channel == "discord"
    assert msg.user_id == "111"
    assert msg.user_display == "Alice"
    assert msg.text == "olá"


def test_incoming_message_optional_fields_default_none():
    """thread_id e raw são opcionais e padrão None."""
    msg = IncomingMessage(channel="slack", user_id="U1", user_display="Bob", text="hi")
    assert msg.thread_id is None
    assert msg.raw is None


def test_incoming_message_with_thread():
    """thread_id pode ser definido."""
    msg = IncomingMessage(
        channel="email",
        user_id="x@y.com",
        user_display="X",
        text="body",
        thread_id="<msg-id@x.y>",
        raw={"headers": {}},
    )
    assert msg.thread_id == "<msg-id@x.y>"
    assert msg.raw == {"headers": {}}


# ── OutgoingMessage ───────────────────────────────────────────────────────────

def test_outgoing_message_defaults():
    """OutgoingMessage requer só text; demais campos têm defaults."""
    msg = OutgoingMessage(text="resposta")
    assert msg.text == "resposta"
    assert msg.thread_id is None
    assert msg.mission_id is None
    assert msg.is_approval is False


def test_outgoing_message_approval_flag():
    """is_approval pode ser True para pedidos de aprovação."""
    msg = OutgoingMessage(text="aprovar?", is_approval=True, mission_id="m-123")
    assert msg.is_approval is True
    assert msg.mission_id == "m-123"


# ── ConfigError ───────────────────────────────────────────────────────────────

def test_config_error_is_exception():
    """ConfigError deve ser uma exceção."""
    err = ConfigError("falta DISCORD_USER_ALLOWLIST")
    assert isinstance(err, Exception)
    assert "falta" in str(err)
