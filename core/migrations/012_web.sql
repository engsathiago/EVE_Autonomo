-- Migration 012: Web UI (F11)
-- Idempotente: usa IF NOT EXISTS em todas as operações.
-- Nota: migration 011 foi ocupada por deploy.sql (F10); web usa 012.

CREATE TABLE IF NOT EXISTS web_sessions (
    id           BIGSERIAL PRIMARY KEY,
    token_hash   TEXT      NOT NULL,
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip           INET      NOT NULL,
    user_agent   TEXT      NOT NULL,
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_open
    ON web_sessions (last_seen_at)
    WHERE closed_at IS NULL;
