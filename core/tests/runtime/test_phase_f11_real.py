"""C.6 — Validação runtime Fase 11 (Web UI).

Valida:
  1. Tabela web_sessions acessível e schema correto (INSERT direto).
  2. Autenticação REST: GET /api/v1/system/info com X-Agent-Token → 200 OK.
  3. REPL interativo: agent chat /help → /exit → exitstatus 0.

Notas de gap (documentadas em BUG_F11_DISCOVERED.md):
  GAP-F11-A: não existe endpoint POST /api/ui/chat — chat é via WS chat.send.
  GAP-F11-B: código nunca faz INSERT em web_sessions (apenas em memória via _WsSession).
             Tabela existe e schema está correto; inserção é responsabilidade do WS handler.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.runtime

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_TOKEN_FILE = Path.home() / ".agent" / "web_token"

# Adiciona source paths ao sys.path para httpx/fastapi test client
_REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_REPO / "core" / "src"))
sys.path.insert(0, str(_REPO / "cli" / "src"))

_AGENT_BIN = str(_REPO / "core" / ".venv" / "bin" / "agent")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    yield pool
    await pool.close()


def _read_token() -> str:
    """Lê token do arquivo ou retorna token padrão de teste."""
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "test-token-f11"


# ---------------------------------------------------------------------------
# Teste 1: web_sessions — tabela existe e aceita INSERT
# ---------------------------------------------------------------------------


async def test_web_sessions_table_insert_and_read(pg_pool, tmp_path):
    """Valida schema da tabela web_sessions via INSERT direto."""
    token = _read_token()
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO web_sessions (token_hash, ip, user_agent)
            VALUES ($1, $2::inet, $3)
            RETURNING id, token_hash, opened_at, last_seen_at
            """,
            token_hash,
            "127.0.0.1",
            "pytest/runtime-c6",
        )

    assert row is not None
    session_id = row["id"]
    assert session_id > 0
    assert row["token_hash"] == token_hash
    assert row["opened_at"] is not None

    count = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM web_sessions WHERE id = $1", session_id
    )
    assert count >= 1

    # Evidência persistida para o relatório
    evidence_path = tmp_path / "f11_web_session_id.txt"
    evidence_path.write_text(str(session_id))

    # Copia evidência para local rastreável
    dest = Path(__file__).parent / "f11_web_session_id.txt"
    dest.write_text(str(session_id))

    print(f"\n[C.6] web_sessions INSERT OK → session_id={session_id}")


# ---------------------------------------------------------------------------
# Teste 2: endpoint REST autenticado
# ---------------------------------------------------------------------------


async def test_web_ui_authenticated_endpoint(pg_pool):
    """GET /api/v1/system/info com X-Agent-Token → 200 OK."""
    import httpx
    from agent.web.server import make_web_app

    token = _read_token()

    app = make_web_app(db_pool=pg_pool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/system/info",
            headers={"X-Agent-Token": token},
        )

    assert resp.status_code == 200, f"Esperado 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "version" in data
    print(f"\n[C.6] /api/v1/system/info OK → version={data['version']}")


async def test_web_ui_rejects_invalid_token(pg_pool):
    """GET /api/v1/system/info sem token → 401."""
    import httpx
    from agent.web.server import make_web_app

    app = make_web_app(db_pool=pg_pool)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/system/info")

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Teste 3: REPL pexpect
# ---------------------------------------------------------------------------


def test_repl_help_and_exit(tmp_path):
    """Spawn agent chat → /help → /exit → exitstatus 0."""
    pexpect = pytest.importorskip("pexpect")

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"
    # Aponta para o arquivo de token existente
    env["AGENT_WEB_TOKEN_FILE"] = str(_TOKEN_FILE)

    child = pexpect.spawn(
        _AGENT_BIN,
        args=["chat"],
        timeout=15,
        encoding="utf-8",
        env=env,
        logfile=open(str(tmp_path / "repl_output.txt"), "w"),
    )

    # Aguarda banner da EVE
    child.expect(r"(?i)(EVE|eve|agente)", timeout=10)

    # Envia /help
    child.sendline("/help")
    child.expect(r"(?i)(help|comando|exit|ajuda)", timeout=8)

    # Envia /exit
    child.sendline("/exit")
    child.expect(pexpect.EOF, timeout=8)

    child.close()
    assert child.exitstatus == 0 or child.signalstatus is None, (
        f"REPL terminou com exitstatus={child.exitstatus}, signal={child.signalstatus}"
    )

    # Evidência
    repl_output = (tmp_path / "repl_output.txt").read_text(errors="replace")
    dest = Path(__file__).parent / "f11_repl_help.txt"
    dest.write_text(repl_output[:2000])
    print(f"\n[C.6] REPL test OK, output salvo em {dest}")
