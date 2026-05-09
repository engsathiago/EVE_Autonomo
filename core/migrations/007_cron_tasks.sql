-- =============================================================================
-- Phase 6: Cron jobs, tasks e observabilidade de subagentes
-- Ordem: cron_jobs → tasks (FK) → subagent_runs (FK)
-- apscheduler_jobs é gerenciada pelo próprio APScheduler (CREATE TABLE IF NOT EXISTS automático)
-- =============================================================================

CREATE TABLE IF NOT EXISTS cron_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    cron_expr   TEXT NOT NULL,
    nl_original TEXT,
    task_tpl    TEXT NOT NULL,
    source      TEXT NOT NULL,
    target      TEXT,
    enabled     BOOLEAN DEFAULT TRUE,
    last_run    TIMESTAMPTZ,
    next_run    TIMESTAMPTZ,
    last_status TEXT,
    last_error  TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cron_jobs_enabled_next
    ON cron_jobs (enabled, next_run);

CREATE TABLE IF NOT EXISTS tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
    cron_job_id   UUID REFERENCES cron_jobs(id) ON DELETE SET NULL,
    source        TEXT NOT NULL,
    content       TEXT NOT NULL,
    tier          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed', 'timeout')),
    result        JSONB,
    error         TEXT,
    iterations    INT DEFAULT 0,
    tokens_in     INT DEFAULT 0,
    tokens_out    INT DEFAULT 0,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_parent
    ON tasks (parent_id);

CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks (status);

CREATE INDEX IF NOT EXISTS idx_tasks_cron_job
    ON tasks (cron_job_id);

CREATE TABLE IF NOT EXISTS subagent_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    parent_task  UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tools_used   TEXT[],
    duration_ms  INT,
    success      BOOLEAN,
    summary      TEXT,
    raw_trace    JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_task
    ON subagent_runs (task_id);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent
    ON subagent_runs (parent_task);
