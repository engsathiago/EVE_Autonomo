"""TDD — ChannelRouter: allowlist, rate limit, dispatch, persistência (C2, C3, C4, C14)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.channels.base import ChannelAdapter, IncomingMessage, OutgoingMessage

# ── Adapter fake para testes ──────────────────────────────────────────────────

class _FakeAdapter(ChannelAdapter):
    name = "fakechan"

    def __init__(self, allowed: list[str]):
        self._allowed = set(allowed)
        self.sent: list[tuple[str, OutgoingMessage]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, user_id: str, msg: OutgoingMessage) -> None:
        self.sent.append((user_id, msg))

    async def is_authorized(self, user_id: str) -> bool:
        return user_id in self._allowed


def _make_router(
    adapter: _FakeAdapter,
    mock_orchestrator,
    mock_approval_manager,
    mock_db_pool,
    approval_channels: list[str] | None = None,
    rate_limit_user: int = 20,
    rate_limit_channel: int = 120,
):
    from agent.channels.router import ChannelRouter
    pool, _ = mock_db_pool
    return ChannelRouter(
        adapters=[adapter],
        orchestrator=mock_orchestrator,
        approval_manager=mock_approval_manager,
        db_pool=pool,
        rate_limit_user_per_min=rate_limit_user,
        rate_limit_channel_per_min=rate_limit_channel,
        approval_channels=approval_channels or ["telegram", "web"],
    )


def _msg(user_id: str = "U1", text: str = "olá") -> IncomingMessage:
    return IncomingMessage(
        channel="fakechan",
        user_id=user_id,
        user_display="Tester",
        text=text,
    )


# ── Allowlist ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_rejects_unauthorized_user(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Usuário fora da allowlist não chega ao orchestrator."""
    adapter = _FakeAdapter(allowed=["U999"])
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, mock_db_pool)

    await router.handle(_msg(user_id="U_BAD"))

    mock_orchestrator.route.assert_not_called()
    # Nenhuma resposta enviada ao usuário não-autorizado
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_router_increments_unauthorized_metric(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Rejeição por allowlist incrementa agent_channel_unauthorized_total."""
    from agent.channels import metrics as ch_metrics

    adapter = _FakeAdapter(allowed=["U999"])
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, mock_db_pool)

    before = ch_metrics.unauthorized_total.labels(channel="fakechan")._value.get()
    await router.handle(_msg(user_id="U_BAD"))
    after = ch_metrics.unauthorized_total.labels(channel="fakechan")._value.get()

    assert after > before


@pytest.mark.asyncio
async def test_router_passes_authorized_user(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Usuário na allowlist chega ao orchestrator."""
    adapter = _FakeAdapter(allowed=["U1"])
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, mock_db_pool)

    await router.handle(_msg(user_id="U1", text="olá"))

    mock_orchestrator.route.assert_called_once()


@pytest.mark.asyncio
async def test_router_sends_response_to_adapter(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Resposta do orchestrator é entregue de volta ao adapter correto."""
    adapter = _FakeAdapter(allowed=["U1"])
    mock_orchestrator.route.return_value = MagicMock(
        final_text="oi de volta", approval_request=None
    )
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, mock_db_pool)

    await router.handle(_msg(user_id="U1", text="olá"))

    assert len(adapter.sent) == 1
    uid, out_msg = adapter.sent[0]
    assert uid == "U1"
    assert "oi de volta" in out_msg.text


# ── Rate limit ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_rate_limit_per_user_blocks_excess(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Mensagens acima do limite por user são bloqueadas (retornam sem chamar orchestrator)."""
    adapter = _FakeAdapter(allowed=["U1"])
    # Limite de 3 por minuto para testar
    router = _make_router(
        adapter, mock_orchestrator, mock_approval_manager, mock_db_pool,
        rate_limit_user=3,
    )

    # Primeiras 3 passam
    for _ in range(3):
        await router.handle(_msg(user_id="U1"))
    route_calls = mock_orchestrator.route.call_count

    # 4ª deve ser bloqueada
    await router.handle(_msg(user_id="U1"))
    assert mock_orchestrator.route.call_count == route_calls  # não aumentou


@pytest.mark.asyncio
async def test_router_rate_limit_per_channel_blocks_excess(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Mensagens acima do limite por canal bloqueiam mesmo com users diferentes."""
    adapter = _FakeAdapter(allowed=["U1", "U2", "U3", "U4"])
    # Limite de 3 por canal por minuto
    router = _make_router(
        adapter, mock_orchestrator, mock_approval_manager, mock_db_pool,
        rate_limit_channel=3,
        rate_limit_user=100,  # user limit alto para não interferir
    )

    # Primeiros 3 passam (de 3 users diferentes)
    for uid in ["U1", "U2", "U3"]:
        await router.handle(_msg(user_id=uid))
    route_calls = mock_orchestrator.route.call_count

    # 4ª mensagem (U4) deve ser bloqueada pelo limite de canal
    await router.handle(_msg(user_id="U4"))
    assert mock_orchestrator.route.call_count == route_calls


@pytest.mark.asyncio
async def test_router_rate_limited_metric_increments(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Bloqueio por rate limit incrementa agent_channel_rate_limited_total."""
    from agent.channels import metrics as ch_metrics

    adapter = _FakeAdapter(allowed=["U1"])
    router = _make_router(
        adapter, mock_orchestrator, mock_approval_manager, mock_db_pool,
        rate_limit_user=1,
    )

    await router.handle(_msg(user_id="U1"))  # passa

    before = ch_metrics.rate_limited_total.labels(channel="fakechan", reason="user")._value.get()
    await router.handle(_msg(user_id="U1"))  # bloqueada
    after = ch_metrics.rate_limited_total.labels(channel="fakechan", reason="user")._value.get()

    assert after > before


# ── Session ID ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_session_id_format(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """session_id deve ser '{channel}:{user_id}'."""
    adapter = _FakeAdapter(allowed=["U42"])
    captured_tasks = []
    mock_orchestrator.route = AsyncMock(side_effect=lambda t: (
        captured_tasks.append(t),
        MagicMock(final_text="ok", approval_request=None)
    )[1])

    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, mock_db_pool)
    await router.handle(_msg(user_id="U42"))

    assert len(captured_tasks) == 1
    assert captured_tasks[0].channel_ref.get("session_id") == "fakechan:U42"


# ── Persistência ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_persists_inbound_message(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Mensagem inbound é gravada em channel_messages com direction=in."""
    pool, conn = mock_db_pool
    adapter = _FakeAdapter(allowed=["U1"])
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, (pool, conn))

    await router.handle(_msg(user_id="U1", text="teste"))

    # Verifica que conn.execute foi chamado ao menos uma vez com 'in'
    calls_sql = [str(c) for c in conn.execute.call_args_list]
    assert any("in" in s for s in calls_sql)


@pytest.mark.asyncio
async def test_router_persists_outbound_message(mock_orchestrator, mock_approval_manager, mock_db_pool):
    """Resposta outbound é gravada em channel_messages com direction=out."""
    pool, conn = mock_db_pool
    mock_orchestrator.route.return_value = MagicMock(
        final_text="resposta", approval_request=None
    )
    adapter = _FakeAdapter(allowed=["U1"])
    router = _make_router(adapter, mock_orchestrator, mock_approval_manager, (pool, conn))

    await router.handle(_msg(user_id="U1", text="teste"))

    calls_sql = [str(c) for c in conn.execute.call_args_list]
    assert any("out" in s for s in calls_sql)


# ── Sem if channel == no router ───────────────────────────────────────────────

def test_router_source_code_has_no_channel_if():
    """C14: router.py não tem 'if.*channel.*==' — roteamento é por adapter, não por nome."""
    import inspect

    from agent.channels import router as router_module
    source = inspect.getsource(router_module)
    # Permitido: comparações em strings de log/persist, não em lógica de dispatch
    lines_with_if_channel = [
        ln for ln in source.splitlines()
        if "if" in ln and "channel" in ln and "==" in ln
        and not ln.strip().startswith("#")
    ]
    assert lines_with_if_channel == [], (
        f"router.py contém 'if channel ==' nas linhas: {lines_with_if_channel}"
    )
