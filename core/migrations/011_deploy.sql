-- Migration 011: Deploy & Operação (F10)
-- Idempotente: usa IF NOT EXISTS em todas as operações.

CREATE TABLE IF NOT EXISTS deploy_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind        TEXT NOT NULL,        -- start|stop|crash|restart|backup|restore|upgrade
    worker      TEXT,                  -- orchestrator|scheduler|api|heartbeat|null
    detail      TEXT,                  -- JSON com contexto
    success     BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deploy_events_ts   ON deploy_events(ts);
CREATE INDEX IF NOT EXISTS idx_deploy_events_kind ON deploy_events(kind);

CREATE TABLE IF NOT EXISTS worker_health (
    worker      TEXT PRIMARY KEY,
    pid         INTEGER,
    started_at  TIMESTAMP,
    last_seen   TIMESTAMP,
    restarts    INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'stopped'  -- running|stopped|flapping|disabled
);
