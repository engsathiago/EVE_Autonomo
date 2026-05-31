# D.1 — Decisões tomadas sem consultar

## 1. Path do módulo de routing

**Spec:** `core/src/agent/execution/tool_routing.py`
**Implementado:** `core/src/agent/orchestrator/tool_router.py`

**Por quê:** `orchestrator/` já contém `router.py` e `tiers.py`. O tool_router é
parte da lógica de orquestração, não de execução (que na arquitetura do projeto
é camada mais baixa com validação de steps). Manter em `orchestrator/` evita
importação circular (execution importa de orchestrator; o contrário não).

## 2. Schema da migration 016

**Spec:** `ALTER TABLE mission_steps ADD COLUMN IF NOT EXISTS tool_set VARCHAR(20)`
**Implementado:** `tools_required JSONB NOT NULL DEFAULT '[]'` + tabela `step_tool_routing`

**Por quê:** `tool_set` enum como VARCHAR limita a declarabilidade — um step pode
precisar de combinação específica (ex: write_file + web_search). JSONB de lista
é mais expressivo. A tabela de auditoria foi adicionada para rastreabilidade sem
custo de query no hot path.

## 3. 4 estratégias vs 1 enum

**Spec:** `ToolSet` enum com 4 valores predefinidos
**Implementado:** resolve em cadeia: declared → keyword → LLM → fallback

**Por quê:** Enum estático não resolve o caso de STRATEGIC que precisa só de
`web_search` (seria over-provisioned com FULL). Cadeia de estratégias dá o set
mínimo necessário por step, reduzindo superfície de ataque em sandboxes.

## 4. MissingRequiredTool no pool (não no executor)

Validação de tools declaradas ocorre em `SubagentPool._run_one` (antes do spawn),
não no executor da missão. Isso permite que o erro seja surfaced com context do
subagent sem mudar a interface do executor.
