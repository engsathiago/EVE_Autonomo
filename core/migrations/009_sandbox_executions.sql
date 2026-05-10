-- =============================================================================
-- Phase 8: Sandboxes de Execução
-- Registra cada execução de comando arbitrário no agente.
-- Stdout/stderr completos: logs/sandbox/<id>.{out,err} (rotação 7 dias).
-- =============================================================================

-- ── UP ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sandbox_executions (
    id                    TEXT PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    policy_name           TEXT NOT NULL,
    backend               TEXT NOT NULL,          -- 'docker' | 'subprocess'
    command_hash          TEXT NOT NULL,           -- sha256[:16] do comando
    command_preview       TEXT NOT NULL,           -- primeiros 200 chars
    exit_code             INTEGER,
    duration_ms           INTEGER,
    memory_peak_mb        REAL,
    cpu_seconds           REAL,
    timed_out             INTEGER NOT NULL DEFAULT 0,
    oom_killed            INTEGER NOT NULL DEFAULT 0,
    network_denied_count  INTEGER NOT NULL DEFAULT 0,
    mission_id            TEXT,                   -- FK lógica → missions.id
    subagent_id           TEXT,                   -- FK lógica → tasks.id
    stdout_preview        TEXT,
    stderr_preview        TEXT
);

CREATE INDEX IF NOT EXISTS idx_sandbox_exec_mission
    ON sandbox_executions(mission_id);

CREATE INDEX IF NOT EXISTS idx_sandbox_exec_created
    ON sandbox_executions(created_at);

CREATE INDEX IF NOT EXISTS idx_sandbox_exec_policy
    ON sandbox_executions(policy_name);

-- =============================================================================
-- DOWN
-- =============================================================================
-- DROP INDEX IF EXISTS idx_sandbox_exec_policy;
-- DROP INDEX IF EXISTS idx_sandbox_exec_created;
-- DROP INDEX IF EXISTS idx_sandbox_exec_mission;
-- DROP TABLE IF EXISTS sandbox_executions;
