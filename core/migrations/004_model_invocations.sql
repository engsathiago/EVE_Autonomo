-- =============================================================================
-- Phase 4: Model Invocations
-- Rastreia cada chamada LLM: provider, modelo, tokens, custo, latência, fallback.
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_invocations (
    id                    BIGSERIAL PRIMARY KEY,
    session_id            UUID REFERENCES conversations(id) ON DELETE CASCADE,
    skill_invocation_id   BIGINT REFERENCES skill_invocations(id) ON DELETE SET NULL,

    provider              TEXT NOT NULL,           -- 'anthropic' | 'openai' | 'openrouter' | 'ollama'
    model                 TEXT NOT NULL,           -- 'claude-sonnet-4-7' | 'qwen2.5:32b' etc.
    model_alias           TEXT,                    -- string original 'provider:model' para debug

    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    total_tokens          INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,

    cost_usd              NUMERIC(10, 6) NOT NULL DEFAULT 0,  -- ollama = 0
    latency_ms            INTEGER NOT NULL DEFAULT 0,

    success               BOOLEAN NOT NULL DEFAULT FALSE,
    error_kind            TEXT,                    -- 'rate_limit' | 'timeout' | 'auth' | 'infra_error' | etc.
    fallback_used         BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_from         TEXT,                    -- modelo original quando houve fallback

    started_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_model_invocations_provider_model
    ON model_invocations (provider, model, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_invocations_session
    ON model_invocations (session_id);

CREATE INDEX IF NOT EXISTS idx_model_invocations_skill
    ON model_invocations (skill_invocation_id);

CREATE INDEX IF NOT EXISTS idx_model_invocations_cost
    ON model_invocations (cost_usd) WHERE cost_usd > 0;
