-- Migration 015: Fase B — validação de execução real
--
-- Alterações:
-- 1. mission_steps: adiciona status 'failed_no_execution' ao CHECK constraint
--    (step marcado assim quando o LLM respondeu só prosa sem invocar nenhuma tool)
-- 2. subagent_runs: adiciona coluna verdict TEXT para registrar ExecutionVerdict
--    (substitui inferência indireta por dado direto de auditoria)
--
-- Reversão: ver seção DOWN no final do arquivo

-- ── UP ───────────────────────────────────────────────────────────────────────

-- 1. Substitui o constraint de status em mission_steps
--    DROP + ADD é o único modo de alterar um CHECK em Postgres sem recriar a tabela.
--    Dados existentes com status = 'done'/'failed' etc. não são afetados.
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
        'failed_no_execution'   -- LLM gerou prosa; nenhuma tool foi chamada
    ));

-- 2. Adiciona coluna verdict em subagent_runs
--    Nullable para compatibilidade com runs existentes (pre-Fase B).
ALTER TABLE subagent_runs
    ADD COLUMN IF NOT EXISTS verdict TEXT;

-- Índice para queries de auditoria: "quantos subagentes terminaram em prose_only?"
CREATE INDEX IF NOT EXISTS idx_subagent_runs_verdict
    ON subagent_runs(verdict)
    WHERE verdict IS NOT NULL;

-- ── DOWN (reversão manual) ───────────────────────────────────────────────────
-- ALTER TABLE mission_steps
--     DROP CONSTRAINT IF EXISTS mission_steps_status_check;
-- ALTER TABLE mission_steps
--     ADD CONSTRAINT mission_steps_status_check
--     CHECK (status IN ('pending','running','done','failed','skipped'));
-- ALTER TABLE subagent_runs DROP COLUMN IF EXISTS verdict;
-- DROP INDEX IF EXISTS idx_subagent_runs_verdict;
