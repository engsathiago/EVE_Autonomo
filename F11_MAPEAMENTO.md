# F11 — Mapeamento de Endpoints Web

## Endpoints que app.js/painéis chamam

| Painel | Endpoint chamado | Método |
|--------|-----------------|--------|
| metrics-bar | `/api/v1/metrics/summary` | GET |
| metrics-bar | `/api/v1/system/info` | GET |
| missions | `/api/v1/missions?status=...&limit=50` | GET |
| skills | `/api/v1/skills?limit=100` | GET |
| memory | `/api/v1/memory/search` | POST |
| traces | `/api/v1/traces?limit=50` | GET |
| critic | `/api/v1/critic/queue?limit=10` | GET |
| critic | `/api/v1/critic/history?limit=10` | GET |
| subagents | `/api/v1/subagents` | GET |
| approvals | `/api/v1/approvals?limit=50` | GET |
| approvals | `/api/v1/approvals/{id}` | POST |
| WebSocket | `/api/v1/stream?token=...` | WS |

## Endpoints que server.py expõe (routes/api.py)

| Endpoint | Status |
|----------|--------|
| `GET /api/v1/missions` | ✓ funcional (retorna 13 missões reais) |
| `POST /api/v1/missions` | ✓ declarado (requer planner) |
| `GET /api/v1/missions/{id}` | ✓ declarado |
| `POST /api/v1/missions/{id}/pause` | ✓ declarado |
| `POST /api/v1/missions/{id}/resume` | ✓ declarado |
| `GET /api/v1/skills` | ✓ funcional (retorna `{"items":[], "total":0}` - nenhuma skill no DB) |
| `GET /api/v1/skills/{name}` | ✓ declarado |
| `POST /api/v1/skills/{name}/disable` | ✓ declarado |
| `POST /api/v1/memory/search` | ✓ declarado (retorna `{"items":[], "total":0}` sem memory_store) |
| `GET /api/v1/traces` | ✓ funcional (retorna `{"items":[], "total":0}`) |
| `GET /api/v1/traces/{id}` | ✓ declarado |
| `GET /api/v1/critic/queue` | ✓ funcional (DB query direta) |
| `GET /api/v1/critic/history` | ✓ funcional (DB query direta) |
| `GET /api/v1/subagents` | ✓ funcional (retorna health com runs recentes) |
| `GET /api/v1/approvals` | ✓ funcional (retorna `{"items":[], "total":0}` sem approval_manager) |
| `POST /api/v1/approvals/{id}` | ✓ declarado |
| `GET /api/v1/metrics/summary` | ✓ funcional (DB query direta) |
| `GET /api/v1/system/info` | ✓ funcional |

## Rotas estáticas (routes/static.py)

| Rota | Arquivo servido | Status |
|------|----------------|--------|
| `GET /` | `webui/public/index.html` | ✓ 200 |
| `GET /css/term.css` | `webui/public/css/term.css` | ✓ |
| `GET /js/app.js` | `webui/public/js/app.js` | ✓ |
| `GET /js/ws.js` | `webui/public/js/ws.js` | ✓ |
| `GET /js/api.js` | `webui/public/js/api.js` | ✓ |
| `GET /js/panels/*.js` | 8 painéis JS | ✓ |

## Diff: quais endpoints faltam

Nenhum endpoint falta. Todos os endpoints chamados pelos painéis existem no
backend. Alguns retornam dados vazios quando o store correspondente não está
instanciado (comportamento esperado — guards `if _xxx is None: return {}`).

## Nota sobre Docker

O container `agent-core-1` já monta `attach_web_routes()` via `server.py`. No
container, `static.py` calcula `_PUBLIC_DIR` como `/webui/public` que não existe
pois o Dockerfile não copia a pasta `webui/`. Para servir localmente, usar
`scripts/run_webui.py` que roda no host onde o path está correto.

Para incluir o webui no Docker, adicionar ao `Dockerfile.python`:
```
COPY webui/public /app/webui/public
```
E ajustar `static.py` para `Path(__file__).parent.parent.parent.parent.parent / "webui" / "public"`
(um `.parent` a menos).
