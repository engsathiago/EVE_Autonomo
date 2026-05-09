-- =============================================================================
-- Phase 5: Adiciona session_id em conversations para get-or-create por canal
-- =============================================================================

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_session_id
    ON conversations (session_id)
    WHERE session_id IS NOT NULL;
