from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from agent.observability.logger import get_logger

log = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 1800  # 30 min


class ApprovalRequest(BaseModel):
    """Retornado pelo SkillRunner quando a skill precisa de aprovação."""

    type: Literal["approval_request"] = "approval_request"
    approval_id: str
    skill_name: str
    summary: str
    expires_at: datetime


class ApprovalState(BaseModel):
    id: str
    session_id: str
    skill_name: str
    skill_args: dict[str, Any]
    summary: str
    channel: str
    channel_ref: dict[str, Any]
    status: Literal["pending", "approved", "rejected", "expired"]
    decided_by: str | None
    decided_at: datetime | None
    expires_at: datetime
    created_at: datetime


class AlreadyDecidedError(Exception):
    """Approval já foi decidido (idempotent — retorna o estado atual)."""

    def __init__(self, state: ApprovalState) -> None:
        self.state = state
        super().__init__(f"Approval {state.id} já está {state.status!r}")


class ApprovalNotFoundError(Exception):
    pass


class ApprovalExpiredError(Exception):
    pass


class ApprovalManager:
    def __init__(self, db_pool: Any, timeout_s: int = _DEFAULT_TIMEOUT_S) -> None:
        self._pool = db_pool
        self._timeout_s = timeout_s
        # Subagentes registram eventos aqui para aguardar decisões de forma async
        self._pending_events: dict[str, asyncio.Event] = {}

    def register_event(self, approval_id: str, event: asyncio.Event) -> None:
        """Subagent registra um Event que será disparado quando a decisão chegar."""
        self._pending_events[approval_id] = event

    def _fire_event(self, approval_id: str) -> None:
        event = self._pending_events.pop(approval_id, None)
        if event is not None:
            event.set()

    async def create(
        self,
        session_id: str,
        skill_name: str,
        skill_args: dict[str, Any],
        summary: str,
        channel: str,
        channel_ref: dict[str, Any] | None = None,
        expires_in_s: int | None = None,
    ) -> ApprovalRequest:
        approval_id = str(uuid.uuid4())
        timeout = expires_in_s if expires_in_s is not None else self._timeout_s
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=timeout)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pending_approvals
                    (id, session_id, skill_name, skill_args, summary, channel, channel_ref, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                approval_id,
                session_id,
                skill_name,
                skill_args,
                summary,
                channel,
                channel_ref or {},
                expires_at,
            )

        log.info("approval.created", approval_id=approval_id, skill=skill_name, session=session_id)
        return ApprovalRequest(
            approval_id=approval_id,
            skill_name=skill_name,
            summary=summary,
            expires_at=expires_at,
        )

    async def get(self, approval_id: str) -> ApprovalState:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM pending_approvals WHERE id = $1",
                approval_id,
            )
        if row is None:
            raise ApprovalNotFoundError(approval_id)
        return ApprovalState(**dict(row))

    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "reject"],
        decided_by: str,
    ) -> ApprovalState:
        now = datetime.now(tz=UTC)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM pending_approvals WHERE id = $1",
                approval_id,
            )
            if row is None:
                raise ApprovalNotFoundError(approval_id)

            state = ApprovalState(**dict(row))

            if state.status != "pending":
                # Idempotente: segunda chamada retorna estado atual sem modificar
                raise AlreadyDecidedError(state)

            if state.expires_at < now:
                await conn.execute(
                    "UPDATE pending_approvals SET status = 'expired' WHERE id = $1",
                    approval_id,
                )
                raise ApprovalExpiredError(approval_id)

            new_status = "approved" if decision == "approve" else "rejected"
            row = await conn.fetchrow(
                """
                UPDATE pending_approvals
                SET status = $2, decided_by = $3, decided_at = $4
                WHERE id = $1
                RETURNING *
                """,
                approval_id,
                new_status,
                decided_by,
                now,
            )

        updated = ApprovalState(**dict(row))
        log.info("approval.decided", approval_id=approval_id, status=new_status, by=decided_by)
        self._fire_event(approval_id)
        return updated

    async def expire_stale(self) -> int:
        """Marca como 'expired' todos os approvals pendentes que já passaram do prazo."""
        now = datetime.now(tz=UTC)
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE pending_approvals
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at < $1
                """,
                now,
            )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            log.info("approval.expired_batch", count=count)
        return count

    async def list_pending(
        self, session_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> list[ApprovalState]:
        async with self._pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM pending_approvals
                    WHERE status = 'pending' AND session_id = $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    session_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM pending_approvals
                    WHERE status = 'pending'
                    ORDER BY created_at DESC LIMIT $1
                    """,
                    limit,
                )
        return [ApprovalState(**dict(r)) for r in rows]
