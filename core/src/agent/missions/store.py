from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from pydantic import BaseModel, Field, field_validator

from agent.observability.logger import get_logger

log = get_logger(__name__)

MissionStatus = Literal["active", "paused", "done", "abandoned", "failed"]
StepStatus = Literal[
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
    "failed_no_execution",   # LLM respondeu prosa sem invocar nenhuma tool (Fase B)
    "failed_missing_tool",   # tool declarada em tools_required não existe no registry (D.1)
    "blocked_by_critic",     # Critic rejeitou tool irreversível antes da execução (D.4)
]
# failed_no_execution: LLM respondeu prosa — problema de execução/prompt.
# failed_missing_tool: ferramenta declarada ausente — problema de configuração.
# blocked_by_critic: Critic rejeitou — problema de segurança/irreversibilidade.
# Distintos para permitir análise separada por causa raiz.

_TERMINAL_STATUSES = {
    "done", "abandoned", "failed",
    "failed_no_execution",   # Fase B
    "failed_missing_tool",   # D.1
    "blocked_by_critic",     # D.4
    "skipped",
}


class Mission(BaseModel):
    id: UUID
    title: str
    objective: str
    success_criteria: list[dict[str, Any]]
    deadline: datetime | None
    status: MissionStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    source: str | None
    source_ref: str | None
    parent_mission_id: UUID | None
    metadata: dict[str, Any]

    @field_validator("success_criteria")
    @classmethod
    def _require_criteria(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("success_criteria não pode ser vazio")
        return v


class MissionStep(BaseModel):
    id: UUID
    mission_id: UUID
    sequence: int
    description: str
    status: StepStatus
    task_id: UUID | None
    retry_count: int
    started_at: datetime | None
    completed_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    # D.1: lista de tools declaradas pelo autor da missão.
    # Lista vazia significa "infere automaticamente" (inferidor de keywords ou LLM).
    tools_required: list[str] = []


class MissionReflection(BaseModel):
    id: UUID
    mission_id: UUID
    delivered: str
    quality_assessment: str
    next_action: str | None
    learned: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class MissionStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        title: str,
        objective: str,
        success_criteria: list[dict],
        deadline: datetime | None,
        source: str,
        source_ref: str | None,
        parent_mission_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> Mission:
        if not success_criteria:
            raise ValueError(
                "success_criteria não pode ser vazio"
                " — missão requer pelo menos um critério verificável"
            )

        mission_id = uuid4()
        now = datetime.now(tz=UTC)

        await self._pool.execute(
            """
            INSERT INTO missions
                (id, title, objective, success_criteria, deadline, status,
                 created_at, updated_at, source, source_ref, parent_mission_id, metadata)
            VALUES ($1, $2, $3, $4::jsonb, $5, 'active', $6, $6, $7, $8, $9, $10::jsonb)
            """,
            mission_id,
            title,
            objective,
            json.dumps(success_criteria, ensure_ascii=False),
            deadline,
            now,
            source,
            source_ref,
            parent_mission_id,
            json.dumps(metadata or {}, ensure_ascii=False),
        )
        log.info("mission.created", mission_id=str(mission_id), title=title)
        return await self.get(mission_id)

    async def get(self, mission_id: UUID) -> Mission:
        row = await self._pool.fetchrow("SELECT * FROM missions WHERE id = $1", mission_id)
        if row is None:
            raise KeyError(f"Mission {mission_id} não encontrada")
        return _row_to_mission(row)

    async def list_active(self) -> list[Mission]:
        rows = await self._pool.fetch(
            "SELECT * FROM missions WHERE status = 'active' ORDER BY created_at"
        )
        return [_row_to_mission(r) for r in rows]

    async def list_by_status(self, status: MissionStatus | None = None) -> list[Mission]:
        if status:
            rows = await self._pool.fetch(
                "SELECT * FROM missions WHERE status = $1 ORDER BY created_at", status
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM missions ORDER BY created_at DESC LIMIT 100"
            )
        return [_row_to_mission(r) for r in rows]

    async def list_by_deadline(self, before: datetime) -> list[Mission]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM missions
            WHERE status = 'active' AND deadline IS NOT NULL AND deadline <= $1
            ORDER BY deadline
            """,
            before,
        )
        return [_row_to_mission(r) for r in rows]

    async def update_status(self, mission_id: UUID, status: MissionStatus) -> None:
        mission = await self.get(mission_id)

        if status in _TERMINAL_STATUSES and mission.parent_mission_id:
            parent = await self.get(mission.parent_mission_id)
            if parent.status not in _TERMINAL_STATUSES:
                raise ValueError(
                    f"Missão filha {mission_id} não pode atingir status terminal "
                    f"enquanto a pai {mission.parent_mission_id} estiver em '{parent.status}'"
                )

        now = datetime.now(tz=UTC)
        completed_at = now if status in _TERMINAL_STATUSES else None

        await self._pool.execute(
            """
            UPDATE missions
               SET status = $2, updated_at = $3,
                   completed_at = COALESCE($4, completed_at)
             WHERE id = $1
            """,
            mission_id,
            status,
            now,
            completed_at,
        )
        log.info("mission.status_updated", mission_id=str(mission_id), status=status)

    async def add_step(
        self,
        mission_id: UUID,
        *,
        description: str,
        sequence: int | None = None,
        tools_required: list[str] | None = None,
    ) -> MissionStep:
        if sequence is None:
            row = await self._pool.fetchrow(
                "SELECT COALESCE(MAX(sequence), -1) + 1 AS next"
                " FROM mission_steps WHERE mission_id = $1",
                mission_id,
            )
            sequence = row["next"]

        step_id = uuid4()
        tools_json = json.dumps(tools_required or [], ensure_ascii=False)
        await self._pool.execute(
            """
            INSERT INTO mission_steps (id, mission_id, sequence, description, status, tools_required)
            VALUES ($1, $2, $3, $4, 'pending', $5::jsonb)
            """,
            step_id,
            mission_id,
            sequence,
            description,
            tools_json,
        )
        return await self._get_step(step_id)

    async def get_pending_steps(self, mission_id: UUID) -> list[MissionStep]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM mission_steps
            WHERE mission_id = $1 AND status = 'pending'
            ORDER BY sequence
            """,
            mission_id,
        )
        return [_row_to_step(r) for r in rows]

    async def get_all_steps(self, mission_id: UUID) -> list[MissionStep]:
        rows = await self._pool.fetch(
            "SELECT * FROM mission_steps WHERE mission_id = $1 ORDER BY sequence",
            mission_id,
        )
        return [_row_to_step(r) for r in rows]

    async def update_step(
        self,
        step_id: UUID,
        *,
        status: StepStatus,
        task_id: UUID | None = None,
        result: dict | None = None,
        error: str | None = None,
        increment_retry: bool = False,
    ) -> None:
        now = datetime.now(tz=UTC)
        started_at = now if status == "running" else None
        completed_at = (
            now
            if status in (
                "done", "failed", "skipped",
                "failed_no_execution", "failed_missing_tool", "blocked_by_critic",
            )
            else None
        )

        await self._pool.execute(
            """
            UPDATE mission_steps
               SET status       = $2,
                   task_id      = COALESCE($3, task_id),
                   result       = COALESCE($4::jsonb, result),
                   error        = COALESCE($5, error),
                   retry_count  = retry_count + $6,
                   started_at   = COALESCE($7, started_at),
                   completed_at = COALESCE($8, completed_at)
             WHERE id = $1
            """,
            step_id,
            status,
            task_id,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            error,
            1 if increment_retry else 0,
            started_at,
            completed_at,
        )

    async def add_reflection(self, mission_id: UUID, reflection: MissionReflection) -> None:
        await self._pool.execute(
            """
            INSERT INTO mission_reflections
                (id, mission_id, delivered, quality_assessment, next_action, learned)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            reflection.id,
            mission_id,
            reflection.delivered,
            reflection.quality_assessment,
            reflection.next_action,
            reflection.learned,
        )
        log.info("mission.reflection_added", mission_id=str(mission_id))

    async def get_critic_history(self, mission_id: UUID) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM critic_evaluations
            WHERE mission_id = $1
            ORDER BY created_at
            """,
            mission_id,
        )
        return [dict(r) for r in rows]

    async def _get_step(self, step_id: UUID) -> MissionStep:
        row = await self._pool.fetchrow("SELECT * FROM mission_steps WHERE id = $1", step_id)
        if row is None:
            raise KeyError(f"MissionStep {step_id} não encontrado")
        return _row_to_step(row)


def _row_to_mission(row: asyncpg.Record) -> Mission:
    criteria = row["success_criteria"]
    if isinstance(criteria, str):
        criteria = json.loads(criteria)
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return Mission(
        id=row["id"],
        title=row["title"],
        objective=row["objective"],
        success_criteria=criteria or [],
        deadline=row["deadline"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        source=row["source"],
        source_ref=row["source_ref"],
        parent_mission_id=row["parent_mission_id"],
        metadata=metadata or {},
    )


def _row_to_step(row: asyncpg.Record) -> MissionStep:
    result = row["result"]
    if isinstance(result, str):
        result = json.loads(result)

    # tools_required: coluna adicionada em D.1 (migration 016).
    # Rows existentes retornam [] por default; rows de DBs sem a coluna
    # (testes unitários com mock) podem não ter o campo — trata graciosamente.
    tools_required_raw = row.get("tools_required", "[]") if hasattr(row, "get") else "[]"
    if tools_required_raw is None:
        tools_required: list[str] = []
    elif isinstance(tools_required_raw, list):
        tools_required = tools_required_raw
    elif isinstance(tools_required_raw, str):
        tools_required = json.loads(tools_required_raw)
    else:
        tools_required = []

    return MissionStep(
        id=row["id"],
        mission_id=row["mission_id"],
        sequence=row["sequence"],
        description=row["description"],
        status=row["status"],
        task_id=row["task_id"],
        retry_count=row["retry_count"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        result=result,
        error=row["error"],
        tools_required=tools_required,
    )
