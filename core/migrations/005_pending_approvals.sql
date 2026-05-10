-- Migration 005: pending approvals + outbound messages audit log

CREATE TABLE IF NOT EXISTS pending_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_args JSONB NOT NULL,
    summary TEXT NOT NULL,
    channel TEXT NOT NULL,
    channel_ref JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_status_expires
    ON pending_approvals (status, expires_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pending_approvals_session
    ON pending_approvals (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outbound_messages_log (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id TEXT,
    channel TEXT NOT NULL,
    payload JSONB NOT NULL,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_log_idempotency
    ON outbound_messages_log (idempotency_key);

CREATE INDEX IF NOT EXISTS idx_outbound_log_undelivered
    ON outbound_messages_log (created_at)
    WHERE delivered = FALSE;
