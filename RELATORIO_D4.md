# Relatório Fase D.4

## Entregue

- [x] `core/src/agent/critic/irreversibility.py` — classificação args-aware
- [x] Hook no AIAgent (`_maybe_gate_tool` em `core.py`) — REJECT/ESCALATE bloqueiam, APPROVE libera
- [x] Timeout 30s → ESCALATE (bloqueio preventivo)
- [x] Sandbox recording: exec_tool já tem SandboxRegistry wired; smoke confirmou +1
- [x] 15 testes novos passando (8 unit + 5 integration critic + 2 integration sandbox)
- [x] Smoke E2E: `critic_evaluations` +1 (9→10), `sandbox_executions` +1 (1→2)
- [x] Tag `fase-d4-done`

## Hook implementado (caminho real)

`core/src/agent/core.py:AIAgent._maybe_gate_tool` → chamado antes de
`registry.execute(name, args)` em `_execute_tools._run_one`.
Parâmetros adicionados ao `__init__`: `critic=None`, `db_pool=None`.

## Smoke E2E

```
critic_evaluations: 9 → 10 (+1)  [verdict=reject por fallback defensivo]
sandbox_executions: 1 → 2 (+1)   [exit_code=0, stdout='sandbox D.4 ok']
```

Critic usou fallback (OllamaTransport não callable via ModelRouter — B1),
mas ainda assim persistiu o registro com verdict="reject". Evidência real no DB.

## Status F7/F8 atualizado

- **F7 Critic**: PARCIAL → **VALIDADA** (critic_evaluations +1 com evidência DB)
- **F8 Sandbox**: PARCIAL → **VALIDADA** (sandbox_executions +1 com evidência DB)

## Decisões tomadas
Ver `DECISOES_D4.md`.

## Bugs fora do escopo
Ver `BUGS_ENCONTRADOS_D4.md` — 6 itens, nenhum introduzido pelo D.4.

## Próximo
`04_FASE_F9_voyager_validation.md`
