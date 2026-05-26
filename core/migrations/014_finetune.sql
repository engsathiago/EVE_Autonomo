-- =============================================================================
-- Phase 13: Fine-tuning local com LoRA + Benchmark Gates
-- Tables: finetune_runs → finetune_checkpoints → benchmark_results
-- Idempotente: usa IF NOT EXISTS em todas as operações.
-- =============================================================================

CREATE TABLE IF NOT EXISTS finetune_runs (
    id               TEXT PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL CHECK (status IN ('running','accepted','rejected','failed')),
    base_model       TEXT NOT NULL,
    checkpoint_id    TEXT,
    dataset_path     TEXT NOT NULL,
    dataset_size     INTEGER NOT NULL,
    benchmark_score  JSONB,
    rejection_reason TEXT,
    triggered_by     TEXT NOT NULL,   -- 'human:thiago' | 'cron:weekly' | 'cli'
    config           JSONB NOT NULL   -- hiperparâmetros: lora_r, lora_alpha, epochs, etc.
);

CREATE INDEX IF NOT EXISTS idx_finetune_runs_status
    ON finetune_runs(status, started_at DESC);

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS finetune_checkpoints (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES finetune_runs(id),
    base_model      TEXT NOT NULL,
    path            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL,
    benchmark_score JSONB NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('candidate','active','archived','rejected')),
    activated_at    TIMESTAMPTZ,
    deactivated_at  TIMESTAMPTZ,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_finetune_checkpoints_state
    ON finetune_checkpoints(state, created_at DESC);

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_results (
    id           TEXT PRIMARY KEY,
    run_id       TEXT REFERENCES finetune_runs(id),  -- NULL para benchmark do base
    model_ref    TEXT NOT NULL,                        -- 'base:qwen2.5-7b' | 'checkpoint:<id>'
    task_id      TEXT NOT NULL,
    score        REAL NOT NULL,
    raw_output   TEXT,
    rubric_axis  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_benchmark_results_model
    ON benchmark_results(model_ref, rubric_axis);

CREATE INDEX IF NOT EXISTS idx_benchmark_results_run
    ON benchmark_results(run_id, rubric_axis)
    WHERE run_id IS NOT NULL;

-- =============================================================================
-- DOWN
-- DROP INDEX IF EXISTS idx_benchmark_results_run;
-- DROP INDEX IF EXISTS idx_benchmark_results_model;
-- DROP TABLE IF EXISTS benchmark_results;
-- DROP INDEX IF EXISTS idx_finetune_checkpoints_state;
-- DROP TABLE IF EXISTS finetune_checkpoints;
-- DROP INDEX IF EXISTS idx_finetune_runs_status;
-- DROP TABLE IF EXISTS finetune_runs;
-- =============================================================================
