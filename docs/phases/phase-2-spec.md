# Fase 2 — Memória Persistente

> **Pré-requisitos:** Fase 0 (estrutura + Docker Compose) e Fase 1 (AIAgent ReAct + tools + `/api/chat`) concluídas.
> **Duração estimada:** 3–5 sessões de Claude Code.
> **Objetivo:** Dar ao agente memória de longo prazo recuperável por similaridade semântica e busca textual, com curadoria automática do que vale a pena persistir e compressão de contextos longos.

---

## 1. Objetivos da Fase

Ao final desta fase, o agente deve ser capaz de:

1. **Persistir conversas** entre sessões em PostgreSQL (não perde nada quando o container reinicia).
2. **Recuperar memórias relevantes** via busca híbrida: vetorial (pgvector) + full-text search (FTS multilingual em português).
3. **Decidir autonomamente o que vale a pena lembrar** via `Curator` (LLM-as-judge usando Haiku 4.5).
4. **Comprimir contextos longos** via `ContextCompressor` quando o histórico ultrapassa um threshold configurável.
5. **Expor duas tools nativas** (`salvar_memoria`, `ler_memoria`) que o agente pode chamar dentro do loop ReAct.
6. **Suportar embeddings multilingual** (PT/EN/ES) via `paraphrase-multilingual-MiniLM-L12-v2` (384 dims).

### Critérios de aceite

- [ ] `docker compose up` sobe Postgres com extensão `vector` + schema aplicado automaticamente.
- [ ] Tool `salvar_memoria` grava texto + embedding + metadata e retorna `memory_id`.
- [ ] Tool `ler_memoria` aceita query em PT/EN/ES e retorna top-K resultados com score.
- [ ] `Curator.should_persist(turn)` retorna decisão estruturada (`{persist: bool, reason: str, importance: int}`).
- [ ] `ContextCompressor.compress(messages)` reduz histórico mantendo fatos críticos.
- [ ] Conversa iniciada na sessão A continua na sessão B com contexto recuperado.
- [ ] Testes unitários em `core/tests/agent/memory/` passam (`pytest -v`).
- [ ] Endpoint `/api/chat` no gateway aceita `conversation_id` opcional e mantém continuidade.

---

## 2. Arquitetura

```
                              ┌──────────────────────────┐
                              │   AIAgent (ReAct loop)   │
                              └────────────┬─────────────┘
                                           │
                  ┌────────────────────────┼─────────────────────────┐
                  │                        │                         │
                  ▼                        ▼                         ▼
         ┌────────────────┐      ┌─────────────────┐       ┌──────────────────┐
         │ salvar_memoria │      │  ler_memoria    │       │ ContextCompressor│
         │     (tool)     │      │     (tool)      │       │  (auto, no loop) │
         └────────┬───────┘      └────────┬────────┘       └────────┬─────────┘
                  │                       │                         │
                  ▼                       ▼                         │
         ┌────────────────┐      ┌─────────────────┐                │
         │    Curator     │      │  MemoryStore    │◄───────────────┘
         │ (Haiku 4.5)    │      │ (vector + FTS)  │
         └────────┬───────┘      └────────┬────────┘
                  │                       │
                  └───────────┬───────────┘
                              ▼
                    ┌──────────────────┐
                    │  PostgreSQL 16   │
                    │   + pgvector     │
                    │   + tsvector     │
                    └──────────────────┘
```

### Fluxo de escrita (turno do usuário → assistente)

1. AIAgent completa um turno (user_msg + assistant_msg + tool_calls).
2. `Curator.should_persist(turn)` avalia se vale a pena persistir.
3. Se `persist=True`, `MemoryStore.save(text, metadata)` gera embedding e grava.
4. Trigger SQL atualiza `tsvector` automaticamente.

### Fluxo de leitura (recuperação contextual)

1. Antes de chamar o LLM, `MemoryStore.search_hybrid(query, k=5)` busca:
   - Top-K vetorial (cosine similarity via pgvector).
   - Top-K FTS (`ts_rank` em portuguese config).
   - Re-rank via Reciprocal Rank Fusion (RRF).
2. Memórias recuperadas são injetadas como `<memoria_relevante>` no system prompt.

### Fluxo de compressão

1. Antes de cada chamada ao LLM, `ContextCompressor.maybe_compress(messages)` checa tokens.
2. Se `total_tokens > threshold` (default: 8000), envia bloco antigo ao Sonnet 4.6 para sumarizar.
3. Substitui mensagens antigas por um único `system: <resumo_da_conversa>...</resumo_da_conversa>`.
4. Sumário é também persistido via `MemoryStore` como `kind='summary'`.

---

## 3. Estrutura de Arquivos

```
core/
├── src/agent/
│   ├── memory/
│   │   ├── __init__.py              # Exporta MemoryStore, Curator, ContextCompressor
│   │   ├── store.py                 # MemoryStore: save, search_vector, search_hybrid
│   │   ├── fts.py                   # Full-text search helpers (tsquery builders)
│   │   ├── curator.py               # Curator: decide o que persistir
│   │   ├── compressor.py            # ContextCompressor: comprime histórico
│   │   ├── embeddings.py            # Wrapper sentence-transformers (singleton)
│   │   └── schemas.py               # Pydantic models: MemoryEntry, CuratorDecision
│   └── tools/builtin/
│       ├── memory_tools.py          # salvar_memoria + ler_memoria
│       └── __init__.py              # registrar as duas tools
├── tests/agent/memory/
│   ├── __init__.py
│   ├── test_store.py
│   ├── test_curator.py
│   ├── test_compressor.py
│   └── test_memory_tools.py
└── migrations/
    └── 002_memory_schema.sql        # schema inicial

gateway/
└── src/routes/
    └── chat.ts                      # atualizar para aceitar conversation_id

docs/phases/
└── phase-2-spec.md                  # este arquivo
```

---

## 4. Schema SQL — `migrations/002_memory_schema.sql`

```sql
-- =============================================================================
-- Phase 2: Memória Persistente
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- -----------------------------------------------------------------------------
-- Conversations: agrupa turnos sob uma sessão lógica
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT,
    user_id         TEXT,                   -- por enquanto opcional, futuro multi-user
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations (updated_at DESC);

-- -----------------------------------------------------------------------------
-- Messages: histórico bruto turno-a-turno (para reconstrução fiel)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content         TEXT NOT NULL,
    tool_calls      JSONB,                  -- p/ assistant turns que chamaram tools
    tool_call_id    TEXT,                   -- p/ tool result turns
    tokens          INTEGER,                -- contagem aproximada
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);

-- -----------------------------------------------------------------------------
-- Memories: itens curados, com embedding vetorial + tsvector
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL DEFAULT 'fact'
                    CHECK (kind IN ('fact', 'preference', 'summary', 'decision', 'note')),
    content         TEXT NOT NULL,
    embedding       VECTOR(384),            -- MiniLM-L12 dim
    importance      SMALLINT NOT NULL DEFAULT 5
                    CHECK (importance BETWEEN 1 AND 10),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv             TSVECTOR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count    INTEGER NOT NULL DEFAULT 0
);

-- Índice vetorial: HNSW para performance em produção
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Índice FTS
CREATE INDEX IF NOT EXISTS idx_memories_tsv
    ON memories USING GIN (tsv);

-- Índices auxiliares
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories (kind);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories (importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_conversation ON memories (conversation_id);

-- -----------------------------------------------------------------------------
-- Trigger: manter tsvector atualizado (portuguese + unaccent)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION memories_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('portuguese', unaccent(coalesce(NEW.content, '')));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memories_tsv ON memories;
CREATE TRIGGER trg_memories_tsv
    BEFORE INSERT OR UPDATE OF content ON memories
    FOR EACH ROW EXECUTE FUNCTION memories_tsv_trigger();

-- -----------------------------------------------------------------------------
-- Trigger: atualizar updated_at em conversations
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION conversations_touch_trigger() RETURNS trigger AS $$
BEGIN
    UPDATE conversations SET updated_at = NOW() WHERE id = NEW.conversation_id;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_messages_touch_conv ON messages;
CREATE TRIGGER trg_messages_touch_conv
    AFTER INSERT ON messages
    FOR EACH ROW EXECUTE FUNCTION conversations_touch_trigger();
```

> **Nota sobre `unaccent`:** o trigger usa `unaccent` para que "memoria" e "memória" caiam no mesmo lexema. Se preferir manter acentos, remova a chamada.

---

## 5. Componentes Python

### 5.1 `core/src/agent/memory/embeddings.py`

```python
"""
Wrapper singleton para sentence-transformers.
Carrega o modelo uma vez por processo (evita reload de ~120MB).
"""
from __future__ import annotations

import threading
from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

_lock = threading.Lock()
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Lazy-load thread-safe."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(text: str) -> List[float]:
    """Gera embedding de um texto. Normaliza para uso com cosine."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_batch(texts: List[str]) -> List[List[float]]:
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return [v.tolist() for v in vecs]
```

**Dependências (adicionar ao `pyproject.toml` / `requirements.txt`):**
```
sentence-transformers>=2.7.0
torch>=2.2.0       # CPU é suficiente para MiniLM
psycopg[binary,pool]>=3.1.18
pgvector>=0.2.5
```

---

### 5.2 `core/src/agent/memory/schemas.py`

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryKind = Literal["fact", "preference", "summary", "decision", "note"]


class MemoryEntry(BaseModel):
    id: UUID | None = None
    conversation_id: UUID | None = None
    kind: MemoryKind = "fact"
    content: str
    importance: int = Field(default=5, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    score: float | None = None  # preenchido em buscas


class CuratorDecision(BaseModel):
    persist: bool
    reason: str
    importance: int = Field(ge=1, le=10)
    kind: MemoryKind = "fact"
    extracted_content: str | None = None  # se Curator quiser reescrever/sintetizar


class SearchResult(BaseModel):
    entries: list[MemoryEntry]
    query: str
    method: Literal["vector", "fts", "hybrid"]
```

---

### 5.3 `core/src/agent/memory/store.py`

```python
"""
MemoryStore: persistência + recuperação híbrida (vetor + FTS).
Usa psycopg3 com pool de conexões.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from .embeddings import embed, EMBEDDING_DIM
from .schemas import MemoryEntry, MemoryKind, SearchResult

log = logging.getLogger(__name__)

DEFAULT_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://agent:agent@postgres:5432/agent",
)


class MemoryStore:
    def __init__(self, dsn: str = DEFAULT_DSN, min_size: int = 2, max_size: int = 10):
        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            configure=self._configure_conn,
            open=False,
        )
        self.pool.open()

    @staticmethod
    def _configure_conn(conn: psycopg.Connection) -> None:
        register_vector(conn)
        conn.row_factory = dict_row

    @contextmanager
    def _conn(self):
        with self.pool.connection() as conn:
            yield conn

    # -------------------------------------------------------------------------
    # Conversations / Messages
    # -------------------------------------------------------------------------
    def create_conversation(self, title: str | None = None,
                            user_id: str | None = None,
                            metadata: dict | None = None) -> UUID:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations (title, user_id, metadata)
                VALUES (%s, %s, %s::jsonb)
                RETURNING id
                """,
                (title, user_id, psycopg.types.json.Jsonb(metadata or {})),
            )
            return cur.fetchone()["id"]

    def append_message(self, conversation_id: UUID, role: str, content: str,
                       tool_calls: dict | None = None,
                       tool_call_id: str | None = None,
                       tokens: int | None = None) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages
                    (conversation_id, role, content, tool_calls, tool_call_id, tokens)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id
                """,
                (
                    conversation_id, role, content,
                    psycopg.types.json.Jsonb(tool_calls) if tool_calls else None,
                    tool_call_id, tokens,
                ),
            )
            return cur.fetchone()["id"]

    def get_messages(self, conversation_id: UUID, limit: int = 100) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, role, content, tool_calls, tool_call_id, tokens, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC, id ASC
                LIMIT %s
                """,
                (conversation_id, limit),
            )
            return cur.fetchall()

    # -------------------------------------------------------------------------
    # Memories: write
    # -------------------------------------------------------------------------
    def save(self, content: str, *,
             kind: MemoryKind = "fact",
             conversation_id: UUID | None = None,
             importance: int = 5,
             metadata: dict | None = None) -> UUID:
        vec = embed(content)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories
                    (conversation_id, kind, content, embedding, importance, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    conversation_id, kind, content, vec, importance,
                    psycopg.types.json.Jsonb(metadata or {}),
                ),
            )
            mem_id = cur.fetchone()["id"]
        log.debug("Memory saved: id=%s kind=%s len=%d", mem_id, kind, len(content))
        return mem_id

    # -------------------------------------------------------------------------
    # Memories: read
    # -------------------------------------------------------------------------
    def search_vector(self, query: str, k: int = 5,
                      kind: MemoryKind | None = None,
                      min_importance: int = 1) -> list[MemoryEntry]:
        qvec = embed(query)
        sql = """
            SELECT id, conversation_id, kind, content, importance, metadata,
                   created_at, 1 - (embedding <=> %s::vector) AS score
            FROM memories
            WHERE importance >= %s
        """
        params: list[Any] = [qvec, min_importance]
        if kind:
            sql += " AND kind = %s"
            params.append(kind)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([qvec, k])

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            self._touch_access([r["id"] for r in rows])
        return [MemoryEntry(**r) for r in rows]

    def search_fts(self, query: str, k: int = 5,
                   kind: MemoryKind | None = None) -> list[MemoryEntry]:
        sql = """
            SELECT id, conversation_id, kind, content, importance, metadata,
                   created_at,
                   ts_rank(tsv, plainto_tsquery('portuguese', unaccent(%s))) AS score
            FROM memories
            WHERE tsv @@ plainto_tsquery('portuguese', unaccent(%s))
        """
        params: list[Any] = [query, query]
        if kind:
            sql += " AND kind = %s"
            params.append(kind)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(k)

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            self._touch_access([r["id"] for r in rows])
        return [MemoryEntry(**r) for r in rows]

    def search_hybrid(self, query: str, k: int = 5,
                      kind: MemoryKind | None = None,
                      rrf_k: int = 60) -> SearchResult:
        """
        Reciprocal Rank Fusion: combina ranking vetorial e FTS.
        score_rrf = sum(1 / (rrf_k + rank_i)) para cada lista em que aparece.
        """
        vec_results = self.search_vector(query, k=k * 2, kind=kind)
        fts_results = self.search_fts(query, k=k * 2, kind=kind)

        scores: dict[UUID, tuple[float, MemoryEntry]] = {}
        for rank, entry in enumerate(vec_results):
            scores[entry.id] = (1.0 / (rrf_k + rank + 1), entry)
        for rank, entry in enumerate(fts_results):
            prev = scores.get(entry.id, (0.0, entry))
            scores[entry.id] = (prev[0] + 1.0 / (rrf_k + rank + 1), prev[1])

        merged = sorted(scores.values(), key=lambda t: t[0], reverse=True)[:k]
        entries = []
        for score, entry in merged:
            entry.score = score
            entries.append(entry)
        return SearchResult(entries=entries, query=query, method="hybrid")

    def _touch_access(self, ids: list[UUID]) -> None:
        if not ids:
            return
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE memories
                SET last_accessed_at = NOW(), access_count = access_count + 1
                WHERE id = ANY(%s)
                """,
                (ids,),
            )

    def close(self) -> None:
        self.pool.close()
```

---

### 5.4 `core/src/agent/memory/curator.py`

```python
"""
Curator: decide se um turno vale a pena persistir.
Usa Haiku 4.5 com prompt estruturado (JSON output).
"""
from __future__ import annotations

import json
import logging

from anthropic import Anthropic

from .schemas import CuratorDecision

log = logging.getLogger(__name__)

CURATOR_MODEL = "claude-haiku-4-5-20251001"

CURATOR_SYSTEM = """\
Você é o Curator de memória de um agente autônomo. Sua função é decidir se um \
turno de conversa contém informação que valha a pena ser lembrada em sessões \
futuras.

CRITÉRIOS PARA PERSISTIR:
- Fatos sobre o usuário (preferências, projetos, contexto profissional/pessoal)
- Decisões tomadas que afetam o futuro (escolhas de stack, arquitetura)
- Resultados de tarefas que podem ser referenciados depois
- Aprendizados sobre o domínio que o agente deve carregar

CRITÉRIOS PARA NÃO PERSISTIR:
- Saudações, agradecimentos, smalltalk
- Perguntas factuais com resposta autocontida
- Conteúdo já trivialmente disponível (ex: "qual a capital da França")
- Redundâncias com memórias já existentes (sinalizadas no contexto)

CLASSIFICAÇÃO `kind`:
- fact: fato objetivo
- preference: preferência/opinião do usuário
- decision: decisão arquitetural/de projeto
- summary: resumo de bloco longo
- note: observação livre

IMPORTANCE (1-10):
- 1-3: trivial, descartável
- 4-6: útil, contexto operacional
- 7-9: crítico, decisões/preferências fortes
- 10: identidade/projeto core

Responda APENAS com JSON válido no formato:
{
  "persist": bool,
  "reason": "explicação curta",
  "importance": int,
  "kind": "fact|preference|decision|summary|note",
  "extracted_content": "texto sintético a salvar (ou null para usar o original)"
}
"""


class Curator:
    def __init__(self, client: Anthropic | None = None,
                 model: str = CURATOR_MODEL):
        self.client = client or Anthropic()
        self.model = model

    def should_persist(self, user_msg: str, assistant_msg: str,
                       existing_memories: list[str] | None = None) -> CuratorDecision:
        ctx_block = ""
        if existing_memories:
            ctx_block = "\n\nMEMÓRIAS JÁ EXISTENTES (evite duplicar):\n" + \
                        "\n".join(f"- {m}" for m in existing_memories[:10])

        user_content = (
            f"TURNO A AVALIAR:\n"
            f"[user]: {user_msg}\n"
            f"[assistant]: {assistant_msg}"
            f"{ctx_block}"
        )

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=CURATOR_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = resp.content[0].text.strip()
            # Limpar fences se vierem
            if raw.startswith("```"):
                raw = raw.strip("`").lstrip("json").strip()
            data = json.loads(raw)
            return CuratorDecision(**data)
        except Exception as e:
            log.warning("Curator failed, defaulting to no-persist: %s", e)
            return CuratorDecision(
                persist=False,
                reason=f"curator_error: {e}",
                importance=1,
            )
```

---

### 5.5 `core/src/agent/memory/compressor.py`

```python
"""
ContextCompressor: comprime histórico longo via Sonnet 4.6.
Mantém últimas N mensagens intactas + sumário das anteriores.
"""
from __future__ import annotations

import logging
from typing import Any

from anthropic import Anthropic

log = logging.getLogger(__name__)

COMPRESSOR_MODEL = "claude-sonnet-4-6-20250514"  # ajustar para slug oficial em uso

COMPRESSOR_SYSTEM = """\
Você é o Compressor de contexto de um agente autônomo. Receberá um bloco de \
mensagens antigas de uma conversa e deve produzir um RESUMO ESTRUTURADO em \
português que preserve:

1. Identidade e contexto do usuário (nome, projeto, stack)
2. Decisões tomadas e suas justificativas
3. Tarefas em andamento e seu status
4. Fatos relevantes mencionados (números, nomes, datas)
5. Tom/preferências de comunicação observados

NÃO inclua:
- Saudações, smalltalk
- Detalhes de execução de tools que já foram resolvidos
- Conteúdo redundante

Formato de saída: prosa estruturada com seções `## Identidade`, `## Decisões`, \
`## Tarefas`, `## Fatos`. Máximo 600 tokens.
"""

DEFAULT_TOKEN_THRESHOLD = 8000
DEFAULT_KEEP_RECENT = 6  # últimas mensagens preservadas como estão


class ContextCompressor:
    def __init__(self, client: Anthropic | None = None,
                 model: str = COMPRESSOR_MODEL,
                 token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
                 keep_recent: int = DEFAULT_KEEP_RECENT):
        self.client = client or Anthropic()
        self.model = model
        self.token_threshold = token_threshold
        self.keep_recent = keep_recent

    @staticmethod
    def _approx_tokens(messages: list[dict]) -> int:
        # heurística: ~4 chars por token; conservador
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 4

    def maybe_compress(self, messages: list[dict[str, Any]]
                       ) -> tuple[list[dict[str, Any]], str | None]:
        """
        Retorna (messages_compactadas, summary_text_ou_None).
        Se nada precisar comprimir, retorna a lista original e None.
        """
        if self._approx_tokens(messages) <= self.token_threshold:
            return messages, None
        if len(messages) <= self.keep_recent + 2:
            return messages, None

        recent = messages[-self.keep_recent:]
        old = messages[:-self.keep_recent]
        # primeiro system fica preservado
        system_msgs = [m for m in old if m.get("role") == "system"]
        old_user_assistant = [m for m in old if m.get("role") != "system"]

        summary = self._summarize(old_user_assistant)
        log.info("Compressed %d msgs into summary (%d chars)",
                 len(old_user_assistant), len(summary))

        compacted = system_msgs + [
            {
                "role": "system",
                "content": f"<resumo_da_conversa>\n{summary}\n</resumo_da_conversa>",
            }
        ] + recent
        return compacted, summary

    def _summarize(self, messages: list[dict]) -> str:
        joined = "\n".join(
            f"[{m.get('role')}]: {m.get('content', '')[:2000]}"
            for m in messages
        )
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=COMPRESSOR_SYSTEM,
            messages=[{"role": "user", "content": joined}],
        )
        return resp.content[0].text.strip()
```

---

### 5.6 `core/src/agent/tools/builtin/memory_tools.py`

```python
"""
Tools nativas para o agente: salvar_memoria + ler_memoria.
Seguem o protocolo de tools definido na Fase 1.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from agent.memory.store import MemoryStore
from agent.memory.schemas import MemoryKind

# Ajustar import conforme a base class de tool definida na Fase 1
from agent.tools.base import Tool, ToolResult  # type: ignore

log = logging.getLogger(__name__)

# Singleton do store; em produção, considerar injetar via container DI
_store: MemoryStore | None = None


def get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


# -----------------------------------------------------------------------------
# salvar_memoria
# -----------------------------------------------------------------------------
class SalvarMemoriaTool(Tool):
    name = "salvar_memoria"
    description = (
        "Salva uma informação na memória de longo prazo do agente. "
        "Use para registrar fatos sobre o usuário, decisões tomadas, "
        "preferências, ou qualquer informação que deva ser lembrada em "
        "sessões futuras. Suporta português, inglês e espanhol."
    )
    input_schema = {
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
                "description": "Metadados livres (tags, contexto extra).",
                "default": {},
            },
        },
        "required": ["content"],
    }

    def __init__(self, conversation_id: UUID | None = None):
        self.conversation_id = conversation_id

    def run(self, **kwargs: Any) -> ToolResult:
        store = get_store()
        try:
            mem_id = store.save(
                content=kwargs["content"],
                kind=kwargs.get("kind", "fact"),
                importance=kwargs.get("importance", 5),
                metadata=kwargs.get("metadata", {}),
                conversation_id=self.conversation_id,
            )
            return ToolResult(
                ok=True,
                output={"memory_id": str(mem_id), "saved": True},
            )
        except Exception as e:
            log.exception("salvar_memoria failed")
            return ToolResult(ok=False, error=str(e))


# -----------------------------------------------------------------------------
# ler_memoria
# -----------------------------------------------------------------------------
class LerMemoriaTool(Tool):
    name = "ler_memoria"
    description = (
        "Busca na memória de longo prazo informações relevantes para uma "
        "consulta. Usa busca híbrida (vetorial + textual). Retorna até K "
        "memórias ordenadas por relevância."
    )
    input_schema = {
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

    def run(self, **kwargs: Any) -> ToolResult:
        store = get_store()
        try:
            result = store.search_hybrid(
                query=kwargs["query"],
                k=kwargs.get("k", 5),
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
        except Exception as e:
            log.exception("ler_memoria failed")
            return ToolResult(ok=False, error=str(e))
```

> **Importante:** ajustar os imports `from agent.tools.base import Tool, ToolResult` para refletir os nomes reais da classe-base definida na Fase 1.

---

### 5.7 Registro das tools — `core/src/agent/tools/builtin/__init__.py`

```python
from .memory_tools import SalvarMemoriaTool, LerMemoriaTool
# ...imports existentes da Fase 1 (filesystem, shell, web_search)

BUILTIN_TOOLS = [
    # Fase 1
    # FilesystemTool(),
    # ShellTool(),
    # WebSearchTool(),
    # Fase 2
    SalvarMemoriaTool(),
    LerMemoriaTool(),
]
```

---

## 6. Integração com o AIAgent

No loop ReAct existente da Fase 1, adicionar três pontos de integração:

### 6.1 Antes de chamar o LLM — recuperação automática

```python
# core/src/agent/aiagent.py (trecho de integração)

def _inject_relevant_memories(self, user_msg: str,
                              messages: list[dict]) -> list[dict]:
    if not self.memory_store:
        return messages
    result = self.memory_store.search_hybrid(user_msg, k=5)
    if not result.entries:
        return messages
    block = "\n".join(
        f"- [{e.kind}, imp={e.importance}] {e.content}"
        for e in result.entries
    )
    sys_block = f"<memorias_relevantes>\n{block}\n</memorias_relevantes>"
    # injetar como system adicional logo após o system principal
    return [messages[0], {"role": "system", "content": sys_block}, *messages[1:]]
```

### 6.2 Antes da chamada — compressão

```python
def _maybe_compress(self, messages: list[dict]) -> list[dict]:
    if not self.compressor:
        return messages
    compacted, summary = self.compressor.maybe_compress(messages)
    if summary and self.memory_store and self.conversation_id:
        self.memory_store.save(
            content=summary,
            kind="summary",
            conversation_id=self.conversation_id,
            importance=6,
        )
    return compacted
```

### 6.3 Depois do turno — curadoria

```python
def _curate_turn(self, user_msg: str, assistant_msg: str) -> None:
    if not (self.curator and self.memory_store):
        return
    decision = self.curator.should_persist(user_msg, assistant_msg)
    if decision.persist:
        content = decision.extracted_content or f"{user_msg}\n→ {assistant_msg}"
        self.memory_store.save(
            content=content,
            kind=decision.kind,
            importance=decision.importance,
            conversation_id=self.conversation_id,
            metadata={"curator_reason": decision.reason},
        )
```

### 6.4 Persistência de mensagens

Toda mensagem trocada no loop deve ser gravada via `store.append_message(...)` para reconstrução fiel.

---

## 7. Gateway: aceitar `conversation_id`

### `gateway/src/routes/chat.ts`

```typescript
// Schema da request
const ChatRequestSchema = z.object({
  message: z.string().min(1),
  conversation_id: z.string().uuid().optional(),
  // ...campos existentes da Fase 1
});

// Handler
export async function chatHandler(req: FastifyRequest, reply: FastifyReply) {
  const body = ChatRequestSchema.parse(req.body);

  // Encaminhar para o core Python
  const response = await fetch(`${CORE_URL}/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: body.message,
      conversation_id: body.conversation_id ?? null,
    }),
  });

  const data = await response.json();
  // data deve incluir conversation_id (criado se não veio)
  return reply.send(data);
}
```

O endpoint correspondente no core (FastAPI) deve:
1. Se `conversation_id` veio, validar e carregar histórico via `store.get_messages(...)`.
2. Senão, criar via `store.create_conversation(...)` e retornar o ID.

---

## 8. Configuração e Variáveis de Ambiente

Adicionar ao `.env` e ao `docker-compose.yml`:

```bash
# Memória
POSTGRES_DSN=postgresql://agent:agent@postgres:5432/agent
MEMORY_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
MEMORY_TOKEN_THRESHOLD=8000
MEMORY_KEEP_RECENT=6
MEMORY_CURATOR_MODEL=claude-haiku-4-5-20251001
MEMORY_COMPRESSOR_MODEL=claude-sonnet-4-6-20250514
```

No `docker-compose.yml`, garantir que o serviço `core` aguarde o `postgres` saudável:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agent
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./core/migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent"]
      interval: 5s
      timeout: 3s
      retries: 10

  core:
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      POSTGRES_DSN: ${POSTGRES_DSN}
      # ...
```

> **Cuidado:** as migrations em `/docker-entrypoint-initdb.d` rodam apenas na primeira inicialização do volume. Para reaplicar, derrube com `docker compose down -v`.

---

## 9. Testes

### 9.1 `core/tests/agent/memory/test_store.py`

Cobertura mínima:
- `test_save_and_retrieve_vector`: salva 3 textos em PT/EN, busca por sinônimo, valida ranking.
- `test_save_and_retrieve_fts`: salva textos com palavras específicas, busca por termo exato.
- `test_hybrid_search_combines_both`: termo presente em FTS mas não semanticamente óbvio aparece no top-K híbrido.
- `test_unaccent`: salvar "memória" e buscar "memoria" deve recuperar.
- `test_filter_by_kind`: salvar 2 facts + 1 preference, busca filtrada retorna só o esperado.

### 9.2 `core/tests/agent/memory/test_curator.py`

- `test_smalltalk_not_persisted`: turno "oi tudo bem?" → `persist=False`.
- `test_user_fact_persisted`: turno onde usuário diz "sou dev em São Paulo" → `persist=True`, `kind=fact`.
- `test_curator_failure_safe`: mock de erro do client retorna decisão `persist=False` sem raise.

### 9.3 `core/tests/agent/memory/test_compressor.py`

- `test_no_compression_below_threshold`: histórico curto retorna inalterado.
- `test_compression_preserves_recent`: histórico longo mantém últimas N mensagens intactas.
- `test_summary_added_as_system`: resumo é injetado como `role=system`.

### 9.4 `core/tests/agent/memory/test_memory_tools.py`

- `test_salvar_memoria_returns_id`: chamada da tool retorna `memory_id` válido.
- `test_ler_memoria_returns_relevant`: salva 3 itens, busca por um deles, retorna no top-1.

### 9.5 Teste de integração end-to-end

`core/tests/integration/test_memory_persistence.py`:
1. Cria conversa A, envia 3 mensagens com fatos.
2. Fecha sessão, recria agente.
3. Cria conversa B, pergunta sobre fato da conversa A.
4. Valida que o fato foi recuperado via `ler_memoria`.

---

## 10. Sequência de Execução (Claude Code)

Sugestão de ordem para o Claude Code aplicar a fase em chunks digestíveis:

1. **Migration + dependências**
   - Criar `migrations/002_memory_schema.sql`.
   - Atualizar `pyproject.toml` / `requirements.txt`.
   - Atualizar `docker-compose.yml`.
   - Validar: `docker compose up postgres` e `\d memories` mostra as colunas.

2. **Embeddings + schemas**
   - Implementar `embeddings.py` e `schemas.py`.
   - Teste manual: `python -c "from agent.memory.embeddings import embed; print(len(embed('teste')))"` → 384.

3. **MemoryStore**
   - Implementar `store.py` completo.
   - Rodar `pytest core/tests/agent/memory/test_store.py -v`.

4. **Curator**
   - Implementar `curator.py`.
   - Rodar testes do Curator (mockando o client Anthropic).

5. **ContextCompressor**
   - Implementar `compressor.py`.
   - Rodar testes (também com mock).

6. **Tools**
   - Implementar `memory_tools.py`.
   - Registrar em `BUILTIN_TOOLS`.
   - Rodar testes das tools.

7. **Integração no AIAgent**
   - Conectar os três pontos (recuperação, compressão, curadoria).
   - Persistir mensagens no `messages`.

8. **Gateway**
   - Atualizar `chat.ts` para aceitar `conversation_id`.
   - Atualizar handler do core.

9. **E2E**
   - Rodar teste de persistência cross-sessão.
   - Smoke test manual via `curl` no gateway.

---

## 11. Métricas e Observabilidade (mínimo viável)

Logar (via logger estruturado já configurado na Fase 1):

- `memory.save`: `{memory_id, kind, importance, content_len, conversation_id}`
- `memory.search`: `{query, method, k, results_count, top_score, latency_ms}`
- `curator.decision`: `{persist, kind, importance, reason, latency_ms}`
- `compressor.applied`: `{messages_in, messages_out, summary_len, latency_ms}`

Em uma fase futura (Fase 4/5), expor essas métricas via Prometheus/OpenTelemetry.

---

## 12. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Embedding model travando o startup do container | Pré-baixar o modelo no Dockerfile (`RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('...')"`). |
| HNSW index lento para inserir em volume | Aceitar para Fase 2; se >100k memórias, considerar IVFFlat ou índice diferido. |
| Curator alucinando JSON malformado | Try/except + fallback `persist=False`; em produção, considerar `response_format` se disponível. |
| Custo excessivo do Curator (1 chamada por turno) | Configurar `CURATOR_ENABLED=false` em dev; usar amostragem (1 a cada N turnos). |
| Compressor perdendo informação crítica | Sempre persistir o sumário como `kind=summary` para fallback de recuperação. |
| Lock contention no pool de conexões | Pool com `max_size=10` é suficiente para 1 instância; revisar quando escalar. |

---

## 13. Não-objetivos (ficam para fases posteriores)

- Compactação/desduplicação periódica (Fase 3+)
- TTL/decay automático de memórias (Fase 3+)
- Autenticação multi-usuário no `user_id` (Fase 5)
- Migração de Postgres para vector DB dedicado (não previsto)
- Reflector usando memórias para autocrítica (Fase 4)

---

## 14. Definition of Done

- [ ] `docker compose up` saudável com schema aplicado.
- [ ] `pytest core/tests/agent/memory/ -v` com 100% verde.
- [ ] Smoke test manual:
  ```bash
  # Sessão 1
  curl -X POST localhost:3000/api/chat \
    -d '{"message":"meu projeto se chama OpenClaw e uso Python+Node"}' \
    -H "Content-Type: application/json"
  # → retorna conversation_id

  # Sessão 2 (novo conversation_id)
  curl -X POST localhost:3000/api/chat \
    -d '{"message":"qual o nome do meu projeto?"}' \
    -H "Content-Type: application/json"
  # → assistente recupera "OpenClaw" via ler_memoria
  ```
- [ ] Logs mostram chamadas de `memory.save`, `memory.search`, `curator.decision`.
- [ ] `docs/phases/phase-2-spec.md` commitado.
- [ ] README atualizado com seção "Memória Persistente".
