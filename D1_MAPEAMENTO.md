# D.1 — Mapeamento do Estado Atual

## Ponto de partida

Branch: `main`, tag `d1-done` já existia antes desta sessão.

## Onde subagents recebem tools hoje

`core/src/agent/subagents/context.py` — `SubAgentContext.tools_allowed: list[str]`
construído por `core/src/agent/orchestrator/router.py` via `resolve_tools_for_step`.

## Onde tools por tier são definidas

`core/src/agent/orchestrator/tool_router.py`:
- `KNOWN_BUILTIN_TOOLS` — frozenset com todas as tools do registry
- `ALWAYS_TOOLS` — sempre incluídas (salvar_memoria, ler_memoria)
- `KEYWORD_TOOL_MAP` — padrões regex → tools inferidas
- `_resolve_fallback(tier)` — fallback seguro por tier

## Onde mission steps definem tools

`SubAgentContext.tools_required: list[str]` — tools declaradas explicitamente.
Migration 016 adicionou `tools_required JSONB` em `mission_steps`.

## Módulo de routing

`core/src/agent/orchestrator/tool_router.py` (383 linhas) implementa 4 estratégias:
1. `declared` — step declarou tools_required explicitamente
2. `inferred_keyword` — regex no description do step
3. `inferred_llm` — Haiku decide (só STRATEGIC/EPIC, cache 7 dias)
4. `fallback_default` — default por tier

## Integração no executor

`core/src/agent/orchestrator/router.py:167–241` — chama `resolve_tools_for_step`
e passa resultado pro `SubAgentContext.tools_allowed` + `tools_required`.

## Integração no subagent runner

`core/src/agent/subagents/pool.py:54–119` — valida `tools_required` via
`validate_declared_tools`, lança `MissingRequiredTool` se alguma tool ausente.

## Testes existentes

- `core/tests/tool_router/test_resolution.py` — 22 testes unitários
- `core/tests/tool_router/test_integration.py` — 4 testes de integração (skipped sem DB)
- `core/tests/orchestrator/test_lint_d1.py` — 8 testes de lint estrutural

Total D.1: 30 passing + 4 skipped (DB)
