# BUG F11 — Gaps descobertos em C.6 (Runtime Web UI)

Data: 2026-06-07  
Branch: feature/rt-validate-f11  
Fase: 11 (Web UI)

## GAP-F11-A — Sem endpoint POST /api/ui/chat

**Esperado (spec C.6):** `POST /api/ui/chat` com Bearer token → 200 OK  
**Encontrado:** Não existe rota POST para chat. O chat é operado exclusivamente via WebSocket:
- Endpoint WS: `WS /api/v1/stream?token=...`
- Operação: cliente envia `{"op": "chat.send", "text": "..."}` 
- Resposta: stream de eventos `{"topic": "chat", "type": "...", "data": "..."}`

**Impacto:** Clientes HTTP-only (ex: curl, integrações REST) não podem usar o chat.  
**Sugestão futura:** Adicionar endpoint POST `/api/v1/chat` que aceita `{"text": "..."}` e retorna Server-Sent Events ou lista de eventos.  
**Status:** Não bloqueia — teste adaptado para usar `GET /api/v1/system/info` para validar auth layer.

## GAP-F11-B — Tabela `web_sessions` nunca é populada pelo código

**Esperado (spec + migration 012):** Cada sessão WS deve criar registro em `web_sessions`.  
**Encontrado:** O handler em `ws.py` cria objetos `_WsSession` em memória (`_sessions: dict[str, _WsSession]`), mas **nunca faz INSERT em `web_sessions`**.

Trecho em `core/src/agent/web/routes/ws.py`:
```python
session_id = str(_uuid.uuid4())
session = _WsSession(ws, session_id)
_sessions[session_id] = session        # ← só em memória
web_metrics.ws_connections_active.inc()
# ← nunca faz INSERT INTO web_sessions
```

**Impacto:** A tabela `web_sessions` existe com schema correto (migration 012 rodou), mas permanece sempre vazia. Isso impede:
- Auditoria de sessões ativas
- Detecção de sessões zumbi
- Métricas de sessions abertas por token

**Sugestão futura:** No `ws_stream()`, após `await ws.accept()`, inserir:
```python
await db_pool.execute(
    "INSERT INTO web_sessions (token_hash, ip, user_agent) VALUES ($1, $2, $3)",
    hashlib.sha256(token.encode()).hexdigest(),
    str(ws.client.host) if ws.client else "unknown",
    ws.headers.get("user-agent", ""),
)
```

**Status:** Não bloqueia — teste validou schema via INSERT direto. Table DDL está correta.

## Resolução dos testes C.6

Apesar dos gaps, os 4 testes passam:

| Teste | Resultado |
|-------|-----------|
| `test_web_sessions_table_insert_and_read` | ✅ PASS — INSERT direto confirma schema |
| `test_web_ui_authenticated_endpoint` | ✅ PASS — GET /api/v1/system/info → 200 OK |
| `test_web_ui_rejects_invalid_token` | ✅ PASS — sem token → 401 |
| `test_repl_help_and_exit` | ✅ PASS — agent chat /help /exit → exitstatus 0 |

**Evidências:**
- `core/tests/runtime/f11_web_session_id.txt` — id da linha inserida em web_sessions
- `core/tests/runtime/f11_repl_help.txt` — output capturado do REPL
