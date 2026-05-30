-- Migration 017: D.4 — blocked_by_critic status + critic_evaluations index
--
-- Alterações:
-- 1. mission_steps: adiciona status 'blocked_by_critic' ao CHECK constraint
--    (step bloqueado pelo Critic antes da execução da tool irreversível)
-- 2. Índice em critic_evaluations(mission_id) para queries de auditoria de órfãs
--
-- Compatibilidade retroativa: rows existentes não são afetados (DROP+ADD do constraint).
-- critic_evaluations.mission_id permanece nullable — Critic pode ser chamado fora de missão.
--
-- Reversão: ver seção DOWN no final do arquivo

-- ── UP ───────────────────────────────────────────────────────────────────────

-- 1. Atualiza CHECK constraint em mission_steps para incluir blocked_by_critic
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
        'failed_no_execution',    -- LLM gerou prosa; nenhuma tool foi chamada (Fase B)
        'failed_missing_tool',    -- tool declarada em tools_required não existe no registry (D.1)
        'blocked_by_critic'       -- Critic rejeitou tool irreversível antes da execução (D.4)
    ));

-- 2. Índice para queries rápidas de órfãs: "quantas evals sem mission_id?"
--    WHERE mission_id IS NOT NULL pula NULL rows (parcial → menor e mais rápido).
CREATE INDEX IF NOT EXISTS idx_critic_evaluations_mission
    ON critic_evaluations(mission_id) WHERE mission_id IS NOT NULL;

-- ── DOWN (reversão manual) ───────────────────────────────────────────────────
-- DROP INDEX IF EXISTS idx_critic_evaluations_mission;
-- ALTER TABLE mission_steps DROP CONSTRAINT IF EXISTS mission_steps_status_check;
-- ALTER TABLE mission_steps
--     ADD CONSTRAINT mission_steps_status_check
--     CHECK (status IN (
--         'pending', 'running', 'done', 'failed', 'skipped',
--         'failed_no_execution', 'failed_missing_tool'
--     ));
