"""
C.1 — Runtime validation Fase 5 (Gateway + pending_approvals)

Valida o fluxo de aprovação end-to-end com infra real:
  1. ApprovalManager.create() → linha em pending_approvals (Postgres real)
  2. ApprovalManager.decide() → status='approved' (mesmo caminho interno do endpoint HTTP)
  3. SELECT status='approved' confirmado no Postgres

Nota sobre o HTTP endpoint:
  O spec permite "POST /v1/approvals/{id} ou via método direto do ApprovalManager".
  O core Docker roda imagem buildada (sem hot-reload) e teria precisado de rebuild
  para pegar as correções de BUG_F5 (json.dumps + _row_to_state). Usar manager.decide()
  diretamente valida o mesmo caminho de dados (Create → DB → Decide → DB) sem
  requerer rebuild do container. O HTTP routing em si é coberto por tests/api/.

Telegram fica fora do escopo: a Fase 5 envolve Telegraf mas validar isso requer
webhook ou instância adaptável. Aqui validamos ApprovalManager → DB → evidência.

NÃO usa mocks de Postgres ou ApprovalManager.
Requer: Postgres em localhost:5432.
Rodar com: pytest -m runtime tests/runtime/test_phase_f5_real.py -v
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from agent.approvals.manager import ApprovalManager

_DSN = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
_EVIDENCE_DIR = Path(__file__).parent / "evidence"

pytestmark = pytest.mark.runtime


@pytest.fixture
async def pg_pool():
    try:
        pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=2, timeout=5)
    except Exception as exc:
        pytest.skip(f"Postgres indisponível em localhost:5432: {exc}")
    yield pool
    await pool.close()


async def test_approval_flow_create_persist_and_decide(pg_pool):
    """
    Fluxo completo de aprovação sem Telegram:
    create → pending_approvals ≥ 1 → decide(approve) → status='approved'
    """
    manager = ApprovalManager(db_pool=pg_pool)

    # 1. Cria pending_approval com skill_args e channel_ref reais (jsonb)
    req = await manager.create(
        session_id="runtime-test-c1",
        skill_name="mock_send_email",
        skill_args={"to": "x@y.com", "subject": "hi", "body": "test body"},
        summary="Enviar email para x@y.com — teste C.1",
        channel="test",
        channel_ref={"chat_id": "123"},
        expires_in_s=300,
    )

    approval_id = req.approval_id

    # 2. SELECT confirma linha existe; campos jsonb são parseáveis como dict
    row = await pg_pool.fetchrow(
        "SELECT * FROM pending_approvals WHERE id = $1",
        approval_id,
    )
    assert row is not None, f"Linha {approval_id!r} não encontrada em pending_approvals"
    assert row["status"] == "pending"
    assert row["skill_name"] == "mock_send_email"

    skill_args_db = row["skill_args"]
    channel_ref_db = row["channel_ref"]
    if isinstance(skill_args_db, str):
        skill_args_db = json.loads(skill_args_db)
    if isinstance(channel_ref_db, str):
        channel_ref_db = json.loads(channel_ref_db)

    assert skill_args_db["to"] == "x@y.com"
    assert channel_ref_db["chat_id"] == "123"

    # COUNT confirma persistência (robusto a clock skew host↔Docker)
    count = await pg_pool.fetchval(
        "SELECT COUNT(*) FROM pending_approvals WHERE id = $1",
        approval_id,
    )
    assert count >= 1, f"Linha {approval_id!r} não encontrada via COUNT"

    # 3. Decide (approve) via manager.decide() — mesmo caminho interno do endpoint HTTP
    state = await manager.decide(
        approval_id=approval_id,
        decision="approve",
        decided_by="runtime-test-c1",
    )
    assert state.status == "approved"
    assert state.decided_by == "runtime-test-c1"

    # 4. SELECT final confirma persistência do status no Postgres
    row = await pg_pool.fetchrow(
        "SELECT id, status, decided_by FROM pending_approvals WHERE id = $1",
        approval_id,
    )
    assert row is not None
    assert row["status"] == "approved", (
        f"Esperado status='approved', obtido {row['status']!r}"
    )
    assert row["decided_by"] == "runtime-test-c1"

    # Evidência
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (_EVIDENCE_DIR / "f5_approval_id.txt").write_text(
        f"approval_id={approval_id}\n"
        f"status=approved\n"
        f"skill_name=mock_send_email\n"
        f"decided_by=runtime-test-c1\n"
    )
