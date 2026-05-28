-- Migration 016: D.1 — Tool routing por step
--
-- Alterações:
-- 1. mission_steps: adiciona coluna tools_required JSONB
--    (lista de tools declaradas pelo autor da missão; default [] = inferência automática)
-- 2. Novo status 'failed_missing_tool' no CHECK constraint de mission_steps
--    (step falhou porque uma tool declarada não existe no registry)
-- 3. Nova tabela step_tool_routing (auditoria de decisão de routing por step)
--
-- Compatibilidade retroativa: tools_required=[] → falls back to inference.
-- Nenhuma migração de dados destrutiva — rows existentes ficam intactas com default [].
--
-- Reversão: ver seção DOWN no final do arquivo

-- ── UP ───────────────────────────────────────────────────────────────────────

-- 1. Adiciona tools_required em mission_steps
ALTER TABLE mission_steps
    ADD COLUMN IF NOT EXISTS tools_required JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 2. Atualiza CHECK constraint para incluir 'failed_missing_tool'
--    DROP + ADD é o único modo de alterar um CHECK em Postgres sem recriar a tabela.
ALTER TABLE mission_steps
    DROP CONSTRAINT IF EXISTS mission_steps_status_check;

ALTER TABLE mission_steps
    ADD CONSTRAINT mission_steps_status_check
    CHECK (status IN (
        'pending',
        'running',
        'done',
        'failed',
        'skipped',
        'failed_no_execution',    -- LLM gerou prosa; nenhuma tool foi chamada (F15/B)
        'failed_missing_tool'     -- tool declarada em tools_required não existe no registry (D.1)
    ));

-- 3. Tabela de auditoria de routing
CREATE TABLE IF NOT EXISTS step_tool_routing (
    id              BIGSERIAL PRIMARY KEY,
    step_id         UUID          NOT NULL REFERENCES mission_steps(id) ON DELETE CASCADE,
    tier            TEXT          NOT NULL,
    tools_declared  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    tools_inferred  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    tools_resolved  JSONB         NOT NULL,
    inference_source TEXT         NOT NULL CHECK (inference_source IN (
                                      'declared',
                                      'inferred_keyword',
                                      'inferred_llm',
                                      'fallback_default'
                                  )),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_step_tool_routing_step
    ON step_tool_routing(step_id);

-- ── DOWN (reversão manual) ───────────────────────────────────────────────────
-- DROP TABLE IF EXISTS step_tool_routing;
-- DROP INDEX IF EXISTS idx_step_tool_routing_step;
-- ALTER TABLE mission_steps DROP COLUMN IF EXISTS tools_required;
-- ALTER TABLE mission_steps DROP CONSTRAINT IF EXISTS mission_steps_status_check;
-- ALTER TABLE mission_steps
--     ADD CONSTRAINT mission_steps_status_check
--     CHECK (status IN ('pending','running','done','failed','skipped',
--                       'failed_no_execution'));
