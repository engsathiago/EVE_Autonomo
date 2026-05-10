-- =============================================================================
-- Phase 7: Missões Persistentes + Crítico Autônomo
-- Ordem de criação: missions → mission_steps (FK missions) → mission_reflections
--                   → reflexive_memory → critic_evaluations
-- DOWN: inverso. Ver seção abaixo.
-- =============================================================================

-- ── UP ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS missions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title             TEXT NOT NULL,
    objective         TEXT NOT NULL,
    success_criteria  JSONB NOT NULL,
    deadline          TIMESTAMPTZ,
    status            TEXT NOT NULL CHECK (status IN ('active','paused','done','abandoned','failed')),
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now(),
    completed_at      TIMESTAMPTZ,
    source            TEXT,
    source_ref        TEXT,
    parent_mission_id UUID REFERENCES missions(id),
    metadata          JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_missions_status
    ON missions(status) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_missions_deadline
    ON missions(deadline) WHERE status = 'active';

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mission_steps (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id   UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    sequence     INT NOT NULL,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending','running','done','failed','skipped')),
    task_id      UUID REFERENCES tasks(id),
    retry_count  INT NOT NULL DEFAULT 0,
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result       JSONB,
    error        TEXT,
    UNIQUE (mission_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_mission_steps_mission
    ON mission_steps(mission_id, sequence);

CREATE INDEX IF NOT EXISTS idx_mission_steps_pending
    ON mission_steps(mission_id, status) WHERE status = 'pending';

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS mission_reflections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id          UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    delivered           TEXT NOT NULL,
    quality_assessment  TEXT NOT NULL,
    next_action         TEXT,
    learned             TEXT NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mission_reflections_mission
    ON mission_reflections(mission_id);

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reflexive_memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight          TEXT NOT NULL,
    source_mission_id UUID REFERENCES missions(id),
    -- EMBEDDING_DIM = 384 (paraphrase-multilingual-MiniLM-L12-v2)
    -- Mantido como 384 para consistência com a memória semântica existente.
    embedding        VECTOR(384),
    relevance_score  FLOAT DEFAULT 0.5,
    forgotten        BOOLEAN DEFAULT FALSE,
    times_recalled   INT DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reflexive_embedding
    ON reflexive_memory USING hnsw (embedding vector_cosine_ops)
    WHERE forgotten = FALSE;

-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS critic_evaluations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id             UUID NOT NULL,
    task_id                 UUID REFERENCES tasks(id),
    mission_id              UUID REFERENCES missions(id),
    technical_verdict       JSONB NOT NULL,
    devils_advocate_verdict JSONB NOT NULL,
    synthesizer_verdict     JSONB NOT NULL,
    final_verdict           TEXT NOT NULL CHECK (
                                final_verdict IN ('approve','reject','approve_with_mitigation','escalate')
                            ),
    mitigations             JSONB,
    latency_ms              INT,
    cost_usd                NUMERIC(10,6),
    created_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_critic_eval_task
    ON critic_evaluations(task_id);

CREATE INDEX IF NOT EXISTS idx_critic_eval_mission
    ON critic_evaluations(mission_id);

CREATE INDEX IF NOT EXISTS idx_critic_eval_decision
    ON critic_evaluations(decision_id);

-- =============================================================================
-- DOWN (executar na ordem inversa para rollback)
-- =============================================================================
-- DROP INDEX IF EXISTS idx_critic_eval_decision;
-- DROP INDEX IF EXISTS idx_critic_eval_mission;
-- DROP INDEX IF EXISTS idx_critic_eval_task;
-- DROP TABLE IF EXISTS critic_evaluations;
--
-- DROP INDEX IF EXISTS idx_reflexive_embedding;
-- DROP TABLE IF EXISTS reflexive_memory;
--
-- DROP INDEX IF EXISTS idx_mission_reflections_mission;
-- DROP TABLE IF EXISTS mission_reflections;
--
-- DROP INDEX IF EXISTS idx_mission_steps_pending;
-- DROP INDEX IF EXISTS idx_mission_steps_mission;
-- DROP TABLE IF EXISTS mission_steps;
--
-- DROP INDEX IF EXISTS idx_missions_deadline;
-- DROP INDEX IF EXISTS idx_missions_status;
-- DROP TABLE IF EXISTS missions;
