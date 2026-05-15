"""Fixtures compartilhadas para testes de canais (F12)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


# ── Mocks de plataformas ─────────────────────────────────────────────────────

@pytest.fixture
def mock_discord_client():
    """Mock de discord.Client — intercepta on_message e métodos de envio."""
    client = MagicMock()
    client.user = MagicMock(id=99999, mention="<@99999>")
    client.guilds = []
    client.is_closed = MagicMock(return_value=False)
    return client


@pytest.fixture
def mock_discord_message():
    """Mensagem Discord sintética com author, content, channel."""
    msg = MagicMock()
    msg.author.id = 111
    msg.author.display_name = "TestUser"
    msg.author.bot = False
    msg.content = "hello"
    msg.channel.send = AsyncMock()
    msg.channel.create_thread = AsyncMock(return_value=MagicMock(
        send=AsyncMock(),
        id="thread-123",
    ))
    msg.guild = MagicMock(id=42)
    msg.attachments = []
    return msg


@pytest.fixture
def mock_slack_app():
    """Mock de AsyncApp do slack-bolt."""
    app = MagicMock()
    app.client = MagicMock()
    app.client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234.5678"})
    app.client.files_upload_v2 = AsyncMock(return_value={"ok": True})
    return app


@pytest.fixture
def mock_slack_event():
    """Evento app_mention sintético do Slack."""
    return {
        "event": {
            "type": "app_mention",
            "user": "U111",
            "text": "<@BOT> hello",
            "ts": "111.222",
            "channel": "C001",
            "thread_ts": None,
        },
        "say": AsyncMock(),
        "client": MagicMock(
            chat_postMessage=AsyncMock(return_value={"ok": True, "ts": "111.333"})
        ),
    }


@pytest.fixture
def mock_imap():
    """Mock de IMAP4_SSL com suporte a IDLE."""
    imap = AsyncMock()
    imap.wait_hello_from_server = AsyncMock()
    imap.login = AsyncMock(return_value=("OK", [b"Logged in"]))
    imap.select = AsyncMock(return_value=("OK", [b"1"]))
    imap.idle_start = AsyncMock()
    imap.idle_done = AsyncMock(return_value=("OK", [b"32 EXISTS"]))
    imap.uid = AsyncMock(return_value=(
        "OK",
        [b"1", b"(RFC822 {123})", b"Subject: [agent] test\r\nFrom: user@example.com\r\n\r\nbody"],
    ))
    imap.logout = AsyncMock()
    imap.protocol = MagicMock()
    imap.protocol.idle_done = AsyncMock(return_value=("OK", []))
    return imap


@pytest.fixture
def mock_smtp():
    """Mock de SMTP async (aiosmtplib)."""
    smtp = AsyncMock()
    smtp.__aenter__ = AsyncMock(return_value=smtp)
    smtp.__aexit__ = AsyncMock(return_value=False)
    smtp.send_message = AsyncMock()
    return smtp


# ── Mocks de infra do agente ────────────────────────────────────────────────

@pytest.fixture
def mock_orchestrator():
    """Mock do Orchestrator — route() retorna AgentResult simples."""
    from unittest.mock import MagicMock
    result = MagicMock()
    result.final_text = "resposta do agente"
    result.approval_request = None

    orc = MagicMock()
    orc.route = AsyncMock(return_value=result)
    return orc


@pytest.fixture
def mock_approval_manager():
    """Mock do ApprovalManager."""
    mgr = AsyncMock()
    mgr.decide = AsyncMock()
    mgr.list_pending = AsyncMock(return_value=[])
    return mgr


@pytest.fixture
def mock_db_pool():
    """Pool asyncpg mockado — retorna (pool, conn) para verificar chamadas."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn
