"""
Testa que ApprovalManager.create() serializa skill_args e channel_ref
como JSON strings antes de passar para asyncpg (colunas jsonb).

Sem Postgres real — mock do pool asyncpg.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.approvals.manager import ApprovalManager


def _make_pool() -> MagicMock:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn)
    return pool, conn


async def test_create_serializes_skill_args_as_json_string() -> None:
    """skill_args dict é passado como json.dumps() string para asyncpg."""
    pool, conn = _make_pool()
    manager = ApprovalManager(db_pool=pool)

    skill_args = {"to": "test@example.com", "subject": "Hi", "body": "Hello"}
    await manager.create(
        session_id="sess-001",
        skill_name="mock_send_email",
        skill_args=skill_args,
        summary="Enviar email",
        channel="telegram",
    )

    conn.execute.assert_called_once()
    call_args = conn.execute.call_args[0]
    # $4 é skill_args — índice 4 nos positional args (query + 8 params)
    # call_args = (query, $1, $2, $3, $4, $5, $6, $7, $8)
    skill_args_passed = call_args[4]

    assert isinstance(skill_args_passed, str), (
        f"skill_args deve ser str (json.dumps), mas foi {type(skill_args_passed).__name__}: {skill_args_passed!r}"
    )
    parsed = json.loads(skill_args_passed)
    assert parsed == skill_args


async def test_create_serializes_channel_ref_as_json_string() -> None:
    """channel_ref dict é passado como json.dumps() string para asyncpg."""
    pool, conn = _make_pool()
    manager = ApprovalManager(db_pool=pool)

    channel_ref = {"chat_id": "123456", "source": "telegram"}
    await manager.create(
        session_id="sess-002",
        skill_name="mock_send_email",
        skill_args={"to": "a@b.com", "subject": "S", "body": "B"},
        summary="Enviar email",
        channel="telegram",
        channel_ref=channel_ref,
    )

    call_args = conn.execute.call_args[0]
    # $7 é channel_ref — índice 7
    channel_ref_passed = call_args[7]

    assert isinstance(channel_ref_passed, str), (
        f"channel_ref deve ser str (json.dumps), mas foi {type(channel_ref_passed).__name__}: {channel_ref_passed!r}"
    )
    parsed = json.loads(channel_ref_passed)
    assert parsed == channel_ref


async def test_create_channel_ref_none_becomes_empty_json_object() -> None:
    """channel_ref=None resulta em '{}' (não em None ou dict vazio)."""
    pool, conn = _make_pool()
    manager = ApprovalManager(db_pool=pool)

    await manager.create(
        session_id="sess-003",
        skill_name="mock_send_email",
        skill_args={"to": "a@b.com", "subject": "S", "body": "B"},
        summary="Enviar email",
        channel="telegram",
        channel_ref=None,
    )

    call_args = conn.execute.call_args[0]
    channel_ref_passed = call_args[7]

    assert isinstance(channel_ref_passed, str)
    assert json.loads(channel_ref_passed) == {}
