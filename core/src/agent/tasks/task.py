from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TaskSource(str, Enum):
    TELEGRAM = "telegram"
    CLI = "cli"
    CRON = "cron"
    SUBAGENT = "subagent"
    API = "api"


@dataclass
class Task:
    content: str
    source: TaskSource | str
    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    cron_job_id: UUID | None = None
    tier: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: dict | None = None
    error: str | None = None
    iterations: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    # Canal de destino para entregar a resposta (ex: chat_id do Telegram)
    channel_target: str | None = None
    # Referência estruturada do canal (ex: {"chat_id": 123, "message_id": 456})
    channel_ref: dict = field(default_factory=dict)
    # D.1: tools declaradas pelo step de missão (propagadas para o orchestrator).
    # Vazio = inferência automática pelo tool_router.
    tools_required: list[str] = field(default_factory=list)

    def result_json(self) -> str | None:
        return json.dumps(self.result, ensure_ascii=False) if self.result is not None else None
