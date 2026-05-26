-- F12: Tabela de auditoria de mensagens por canal extra (Discord, Slack, Email).
-- Todas as mensagens in/out passam por aqui antes de qualquer processamento.
-- Serve como trilha de auditoria e input para busca semântica (F9).

CREATE TABLE IF NOT EXISTS channel_messages (
    id          BIGSERIAL PRIMARY KEY,
    channel     TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    user_id     TEXT NOT NULL,
    user_display TEXT,
    text        TEXT NOT NULL,
    thread_id   TEXT,
    mission_id  TEXT,
    session_id  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_channel_messages_channel
    ON channel_messages (channel, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_channel_messages_mission
    ON channel_messages (mission_id)
    WHERE mission_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_channel_messages_session
    ON channel_messages (session_id);
