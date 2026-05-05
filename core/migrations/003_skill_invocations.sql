-- =============================================================================
-- Phase 3: Skill Invocations
-- =============================================================================

CREATE TABLE IF NOT EXISTS skill_invocations (
    id           BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    skill_name   TEXT NOT NULL,
    skill_version INTEGER NOT NULL DEFAULT 1,
    arguments    JSONB NOT NULL,
    result       JSONB,
    success      BOOLEAN NOT NULL DEFAULT FALSE,
    error        TEXT,
    latency_ms   INTEGER,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_skill_invocations_skill
    ON skill_invocations (skill_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_skill_invocations_session
    ON skill_invocations (session_id);
