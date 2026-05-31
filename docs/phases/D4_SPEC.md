# D.4 — Critic no mission flow + D.1 no MissionExecutor

> Sub-fase D do agente autônomo. Pré-requisito: `d1-done`, `d2-done`, `d3-done` em main. Branch `validate/d5-runtime-revalidation` aguardando review (decisão: cherry-pick dos 2 fixes de container antes de começar D.4).

---

## 1. Contexto

A D.5 (re-validação) entregou 4/9 destrancadas, abaixo do threshold de 5. O achado mais relevante: **D.1 não foi propagada para o `MissionExecutor`**. Quando você fechou `d1-done`, o replay C10 validou no caminho de tasks/cron, mas o caminho de missions ficou de fora. `step_tool_routing=0` nas missões F7 prova isso.

F7 falhou por **dois** motivos sobrepostos:

1. **D.1 incompleta:** steps do mission flow ainda recebem tools por tier fixo (estado pré-D.1). Quando o LLM responde "essa tool não está disponível", continua acontecendo no mission path.
2. **Critic não wired:** mesmo se a tool chegasse, decisões irreversíveis passariam sem revisão. 9 `critic_evaluations` órfãs continuam órfãs.

A D.4 conserta os dois numa sub-fase só porque resolver um sem o outro deixa F7 ainda teórica. Critic sem D.1 = step nunca chega ao Critic (falha por tool ausente antes). D.1 sem Critic = step roda, mas irreversíveis passam sem revisão.

A D.4 **não** mexe em F9 (perms — sub-fase própria), **não** mexe em F11 (refactor middleware — sub-fase própria), **não** mexe em F12 (credenciais — não é dívida de código).

---

## 2. Objetivos

1. Cherry-pick dos 2 fixes de container (parents[4] → settings.skills_dir; mkdir dentro do try) da branch `validate/d5-runtime-revalidation` para `main`.
2. Propagar `ToolRouter.resolve_tools_for_step()` (da D.1) para o `MissionExecutor`, antes de spawn do subagent.
3. Wire do Critic em `AIAgent._execute_tools()` — intercepta tool específica, não dispatch genérico (conforme `BUG_PATTERN_MAP.md` da Fase B).
4. Adicionar status terminal `blocked_by_critic` em `mission_steps.status` (nova migration).
5. Garantir que `critic_evaluations` ganha `mission_id` e `task_id` populados (eliminar órfãs).
6. Logar decisão em `step_tool_routing` também no mission flow (auditoria).
7. Re-rodar F7 do plano D.5 e provar destravamento com evidência.

**Não-objetivos:**
- Não cria novas personas do Conclave (já são 3).
- Não muda threshold do Critic (configurável via env, fora de escopo).
- Não toca em F8/F9/F11/F12.
- Não faz fine-tuning, evolução, ou prompt engineering avançado.

---

## 3. Arquivos a tocar

```
core/migrations/017_blocked_by_critic.sql        ← novo (status + critic FK)
core/src/agent/missions/executor.py              ← integra ToolRouter + Critic
core/src/agent/core.py                           ← hook do Critic em _execute_tools
core/src/agent/critic/__init__.py                ← API pública (se não existir)
core/src/agent/critic/irreversible.py            ← já existe, só usa
core/src/agent/missions/schema.py                ← novo status enum
core/tests/missions/test_executor_d1.py          ← unit: D.1 no mission flow
core/tests/missions/test_executor_critic.py      ← unit: Critic blocking
core/tests/missions/test_executor_integration.py ← integration end-to-end
core/tests/regression/test_no_orphan_critic.py   ← regressão: critic_evaluations.mission_id != NULL
core/docs/phases/D4_NOTES.md                     ← decisões, edge cases
core/docs/phases/D4_REPLAY_RESULTS.md            ← replay F7 da D.5
```

---

## 4. Critérios de aceite (C1 a C12)

**C1.** Migration 017 cria status `blocked_by_critic` em `mission_steps.status` CHECK constraint sem dropar dados existentes.

**C2.** `MissionExecutor._prepare_step()` chama `tool_router.resolve_tools_for_step(step)` antes de spawn do subagent. `step_tool_routing` ganha linha por step.

**C3.** Steps com tool inferida ausente do registry → `failed_missing_tool` (consistente com cron/orchestrator).

**C4.** `AIAgent._execute_tools()` consulta `critic.is_irreversible(tool_name)` antes de cada tool call. Se irreversível → chama `critic.evaluate(Decision(tool_name=real_name, tier=...))`.

**C5.** Se Critic rejeita → step vai para `blocked_by_critic`, mission continua (não trava), tool **não executa**.

**C6.** Toda `critic_evaluations` criada via mission flow tem `mission_id` E `task_id` (step_id) não-NULL.

**C7.** `exec_tool` continua sendo ponto único de execução. Não regredir F8.

**C8.** Suite anterior continua verde: testes de D.1, D.2, D.3 não quebram.

**C9.** Pelo menos 6 testes novos: 2 unit D.1 no mission, 2 unit Critic, 1 integration end-to-end, 1 regressão de órfãs.

**C10.** Replay F7 da D.5: missão "remove /tmp/d5_test_dir" → step com tool `exec_tool` (rm é irreversível) → Critic chamado → comportamento esperado (rejeição ou aprovação documentada).

**C11.** `critic_evaluations` na sessão de replay tem `mission_id` populado em 100% das linhas novas.

**C12.** `step_tool_routing` tem linha por step da missão de replay (não pode ser 0 como em D.5).

---

## 5. Anti-padrões (proibido)

1. **Critic em dispatch genérico.** Já tentamos antes — `tool_name="orchestrator_dispatch"` nunca casa com lista de irreversíveis. Hook tem que ser por tool específica.
2. **D.1 duplicada.** Não reimplementa `ToolRouter` — usa o que está em `agent/tool_router/`.
3. **Skip-critic via flag.** Pode ajustar threshold, não pode desligar. Em dev, warning gritante no log se configurado fraco.
4. **Critic auto-aprovando.** Se Conclave divergir e Sintetizador escolher aprovar, log explícito + razão. Se >80% aprovação em 24h, log warning de "rubber stamp".
5. **Bloqueio silencioso.** `blocked_by_critic` sempre vem com `result.error_message` legível pra humano + linha em `critic_evaluations` com `final_verdict` + `reasoning`.
6. **Mission travada.** Se um step bloquear, mission continua nos próximos (não trava todos). Mission só vai para `failed` se TODOS os steps falharem.

---

## 6. Migration 017

```sql
-- 017_blocked_by_critic.sql
BEGIN;

ALTER TABLE mission_steps DROP CONSTRAINT IF EXISTS mission_steps_status_check;
ALTER TABLE mission_steps ADD CONSTRAINT mission_steps_status_check
  CHECK (status IN (
    'pending', 'running', 'done', 'failed',
    'failed_no_execution',    -- Fase B
    'failed_missing_tool',    -- D.1
    'blocked_by_critic',      -- D.4 (NEW)
    'skipped'
  ));

-- critic_evaluations já tem mission_id/task_id na schema, mas eram nullable.
-- Não force NOT NULL (compat com Critic chamado fora de mission).
-- Apenas adiciona índice pra query rápida das órfãs.
CREATE INDEX IF NOT EXISTS idx_critic_evaluations_mission
  ON critic_evaluations(mission_id) WHERE mission_id IS NOT NULL;

COMMIT;
```

---

## 7. Próximos passos depois de D.4

Se D.4 destrancar F7 com evidência:
- **D.6** — F9 perms (skills_dir writable) + reabilitar `/api/v1/skills`
- **D.7** — F11 refactor middleware (sub-app ou pre-startup mount)
- **D.5 re-replay** — rodar de novo o plano D.5 com D.4 + D.6 + D.7 aplicadas

Se D.5 re-replay der ≥6/9 → tag `d5-done` e segue para Fase C (deploy controlado VPS).

Se ainda <6 → análise honesta do que sobrou ser teórico e decisão de descontinuar/refazer.
