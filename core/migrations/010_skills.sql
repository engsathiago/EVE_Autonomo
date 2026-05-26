-- =============================================================================
-- Phase 9: Skills Auto-Geradas
-- Registra skills geradas pelo agente, candidatas, execuções por skill.
-- Embedding armazenado como bytea (numpy float32 serializado) — cosine em Python.
-- =============================================================================

-- ── UP ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS skills (
    slug                TEXT PRIMARY KEY,
    version             INTEGER NOT NULL DEFAULT 1,
    status              TEXT NOT NULL CHECK (status IN (
                            'pending','active','rejected',
                            'deprecated','flagged_for_review','mature'
                        )),
    manifest_json       TEXT NOT NULL,
    embedding           BYTEA,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_at         TIMESTAMPTZ,
    last_used_at        TIMESTAMPTZ,
    executions_count    INTEGER NOT NULL DEFAULT 0,
    successes_count     INTEGER NOT NULL DEFAULT 0,
    failures_count      INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL,
    critic_approval_id  TEXT,
    rejection_reason    TEXT
);

CREATE TABLE IF NOT EXISTS skill_executions (
    id                  TEXT PRIMARY KEY,
    skill_slug          TEXT NOT NULL REFERENCES skills(slug),
    sandbox_execution_id TEXT REFERENCES sandbox_executions(id),
    mission_id          TEXT,
    input_json          TEXT NOT NULL,
    output_json         TEXT,
    success             BOOLEAN NOT NULL,
    duration_seconds    REAL NOT NULL,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_candidates (
    id                      TEXT PRIMARY KEY,
    proposed_slug           TEXT NOT NULL,
    source_execution_ids    TEXT NOT NULL,   -- JSON array de sandbox_execution.id
    pattern_cluster_score   REAL NOT NULL,
    llm_synthesis_prompt    TEXT,
    llm_synthesis_response  TEXT,
    validation_report_json  TEXT,
    status                  TEXT NOT NULL CHECK (status IN (
                                'synthesizing','validating','approved','rejected'
                            )),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_skills_status
    ON skills(status);

CREATE INDEX IF NOT EXISTS idx_skill_executions_slug
    ON skill_executions(skill_slug, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_skill_candidates_status
    ON skill_candidates(status, created_at DESC);

-- =============================================================================
-- DOWN
-- =============================================================================
-- DROP INDEX IF EXISTS idx_skill_candidates_status;
-- DROP INDEX IF EXISTS idx_skill_executions_slug;
-- DROP INDEX IF EXISTS idx_skills_status;
-- DROP TABLE IF EXISTS skill_candidates;
-- DROP TABLE IF EXISTS skill_executions;
-- DROP TABLE IF EXISTS skills;
