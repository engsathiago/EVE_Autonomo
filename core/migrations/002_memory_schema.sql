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
    user_id         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations (updated_at DESC);

-- -----------------------------------------------------------------------------
-- Messages: histórico bruto turno-a-turno
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system')),
    content         TEXT NOT NULL,
    tool_calls      JSONB,
    tool_call_id    TEXT,
    tokens          INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);

-- -----------------------------------------------------------------------------
-- Memories: itens curados com embedding vetorial + tsvector
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
    kind             TEXT NOT NULL DEFAULT 'fact'
                     CHECK (kind IN ('fact', 'preference', 'summary', 'decision', 'note')),
    content          TEXT NOT NULL,
    embedding        VECTOR(384),
    importance       SMALLINT NOT NULL DEFAULT 5
                     CHECK (importance BETWEEN 1 AND 10),
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv              TSVECTOR,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count     INTEGER NOT NULL DEFAULT 0
);

-- HNSW para busca vetorial em produção
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_memories_tsv
    ON memories USING GIN (tsv);

CREATE INDEX IF NOT EXISTS idx_memories_kind        ON memories (kind);
CREATE INDEX IF NOT EXISTS idx_memories_importance  ON memories (importance DESC);
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
-- Trigger: atualizar updated_at em conversations a cada nova mensagem
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
