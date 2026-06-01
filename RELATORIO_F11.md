# Relatório Fase F11

## Entregue

- [x] `scripts/run_webui.py` — servidor local na porta 8080 com pool Postgres real
- [x] 8 endpoints funcionais em `agent.web.server`/`agent.web.routes.api`:
  - `/api/v1/missions` (dados reais: 13 missões)
  - `/api/v1/skills` (funcional, 0 skills no DB)
  - `/api/v1/critic/queue` + `/api/v1/critic/history`
  - `/api/v1/subagents`
  - `/api/v1/approvals`
  - `/api/v1/metrics/summary`
  - `/api/v1/traces`
  - `/api/v1/system/info`
- [x] 8 painéis completos em `webui/public/`:
  - CHAT, MISSÕES, SKILLS, MEMÓRIA, TRACES, CRÍTICO, SUBAGENTES, APROVAÇÕES
- [x] Auth por token HMAC (X-Agent-Token, arquivo `~/.agent/web_token`)
- [x] 12 testes de integração novos — todos passando
- [x] Smoke E2E: raiz `/` retorna 200, 8/8 endpoints retornam 200 com JSON
- [x] Tag `fase-f11-done`

## Painéis funcionais

| Painel | Estado |
|--------|--------|
| MISSÕES | ✓ populado (13 missões reais do DB) |
| CRÍTICO | ✓ funcional (fila + histórico) |
| SUBAGENTES | ✓ funcional (health + runs recentes) |
| APROVAÇÕES | ✓ funcional (lista pending) |
| SKILLS | ✓ funcional (DB tem 0 skills, 2 candidates) |
| TRACES | ✓ funcional (lista tasks) |
| MEMÓRIA | ✓ funcional (search semântico) |
| CHAT | ✓ funcional via WS |

## Estado F11

PARCIAL → **VALIDADA**

O backend `agent.web.server.make_web_app()` e todas as rotas REST existiam e
funcionavam. A web UI em `webui/public/` estava completa com 8 painéis. Esta
fase validou a integração E2E, criou o script de desenvolvimento local e os
testes de integração formais.

## Decisões

Ver `F11_MAPEAMENTO.md` para mapeamento completo de endpoints.

**Decisão principal:** servidorno host (não no Docker) para desenvolvimento
local, pois `Dockerfile.python` não copia `webui/public/`. O script
`scripts/run_webui.py` conecta ao Postgres Docker via `localhost:5432`.

## Bugs fora do escopo

- **Docker webui:** O container `agent-core-1` (porta 8000) não serve o
  frontend porque `Dockerfile.python` não copia `webui/public/`. Corrigir
  adicionando `COPY webui/public /app/webui/public` ao Dockerfile. Marcado
  como TODO F11.1.

- **SkillManager no script local:** Para mostrar skills reais no painel SKILLS
  seria necessário instanciar `SkillManager` com um transport LLM, o que requer
  API key e é complexo para desenvolvimento local. O painel mostra "Nenhuma
  skill" quando o DB não tem skills sintetizadas. Marcado como TODO F11.1.

## Próximo

`06_FASE_INFRA_ci_migrations.md`
