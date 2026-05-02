"""
Tools nativas: salvar_memoria + ler_memoria.
Seguem o protocolo BaseTool da Fase 1 (async execute).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from agent.memory.schemas import MemoryKind
from agent.memory.store import MemoryStore
from agent.observability.logger import get_logger
from agent.tools.base import BaseTool, ToolResult

log = get_logger(__name__)


class SalvarMemoriaTool(BaseTool):
    name = "salvar_memoria"
    description = (
        "Salva uma informação na memória de longo prazo do agente. "
        "Use para registrar fatos sobre o usuário, decisões tomadas, "
        "preferências, ou qualquer informação que deva ser lembrada em "
        "sessões futuras. Suporta português, inglês e espanhol."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Texto a ser salvo na memória.",
            },
            "kind": {
                "type": "string",
                "enum": ["fact", "preference", "decision", "summary", "note"],
                "default": "fact",
                "description": "Tipo da memória.",
            },
            "importance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
                "description": "Importância (1=trivial, 10=crítico).",
            },
            "metadata": {
                "type": "object",
                "description": "Metadados livres.",
                "default": {},
            },
        },
        "required": ["content"],
    }

    def __init__(self, store: MemoryStore, conversation_id: UUID | None = None) -> None:
        self._store = store
        self._conversation_id = conversation_id

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            mem_id = await self._store.save(
                content=kwargs["content"],
                kind=kwargs.get("kind", "fact"),
                importance=int(kwargs.get("importance", 5)),
                metadata=kwargs.get("metadata", {}),
                conversation_id=self._conversation_id,
            )
            return ToolResult(ok=True, output={"memory_id": str(mem_id), "saved": True})
        except Exception as exc:
            log.exception("salvar_memoria.failed")
            return ToolResult(ok=False, error=str(exc))


class LerMemoriaTool(BaseTool):
    name = "ler_memoria"
    description = (
        "Busca na memória de longo prazo informações relevantes para uma consulta. "
        "Usa busca híbrida (vetorial + textual). Retorna até K memórias ordenadas por relevância."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Consulta em linguagem natural (PT/EN/ES).",
            },
            "k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "kind": {
                "type": "string",
                "enum": ["fact", "preference", "decision", "summary", "note"],
                "description": "Filtrar por tipo (opcional).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = await self._store.search_hybrid(
                query=kwargs["query"],
                k=int(kwargs.get("k", 5)),
                kind=kwargs.get("kind"),
            )
            return ToolResult(
                ok=True,
                output={
                    "query": result.query,
                    "method": result.method,
                    "results": [
                        {
                            "id": str(e.id),
                            "kind": e.kind,
                            "content": e.content,
                            "importance": e.importance,
                            "score": round(e.score or 0.0, 4),
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in result.entries
                    ],
                },
            )
        except Exception as exc:
            log.exception("ler_memoria.failed")
            return ToolResult(ok=False, error=str(exc))
