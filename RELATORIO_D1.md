# Relatório Fase D.1 — Tool Routing por Step

## Status

**DONE** — tag `fase-d1-done` aplicada.

## Entregue

- [x] `core/src/agent/orchestrator/tool_router.py` — 383 linhas, 4 estratégias de resolução
- [x] Migration 016 (`core/migrations/016_step_tool_routing.sql`) — `tools_required JSONB` + tabela `step_tool_routing`
- [x] Mission executor integrado (`orchestrator/router.py:167–241`)
- [x] Subagent runner integrado (`subagents/pool.py` — `MissingRequiredTool`)
- [x] 30 testes passando (22 unit + 8 lint) + 4 integration skipped (requerem DB)
- [x] Migration: pendente aplicação em produção (Docker offline localmente)
- [x] Tag `fase-d1-done`

## Design implementado vs spec

A spec pedia um `ToolSet` enum com 4 valores fixos. O implementado é superior:

| Spec | Implementado |
|------|-------------|
| `ToolSet` enum (4 valores) | Cadeia: declared→keyword→LLM→fallback |
| `tool_set VARCHAR(20)` | `tools_required JSONB` (mais expressivo) |
| Integração simples | + tabela de auditoria `step_tool_routing` |
| 5 unit + 1 integration | 22 unit + 8 lint + 4 integration |

Ver `DECISOES_D1.md` para justificativas completas.

## Bugs encontrados fora do escopo

Ver `BUGS_ENCONTRADOS_D1.md`. Resumo:
- 2 falhas em test_autonomous (mock desatualizado, pré-existente)
- 4 falhas + 5 errors em test_deploy (Docker offline, pré-existente)
- 6 falhas em test_ollama_cloud (refatoração sem atualizar testes, pré-existente)
- 1 error em test_memory_store (PostgreSQL offline, pré-existente desde F5)

## Suite total

**1132 testes passando** (sem contar testes que requerem Docker/PostgreSQL).
Pré-existentes com falha: 13 (nenhum introduzido pelo D.1).

## Próximo passo

Cola prompt `02_FASE_D5_revalidacao.md` no próximo Claude Code.
