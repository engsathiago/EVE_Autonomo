# F11 — Web UI (Dashboard estilo terminal)

> Fase 11 do agente autônomo. Pré-requisito: F10 fechada na tag `phase-10-done`, com agente rodando como serviço gerenciado, `/health` e `/metrics` no ar, backup diário funcionando.

---

## 1. Contexto

Até a F10 o operador interage com o agente por CLI, logs JSON, Telegram e `/metrics`. Funciona, mas é cego pra muita coisa que o sistema sabe: skills auto-geradas pela F9, busca semântica na memória vetorial, traces estruturados por missão, fila do Crítico, health dos subagentes, aprovações pendentes do Telegram, missões persistentes ativas, métricas de evolução.

A F11 expõe tudo isso num painel web local — **dashboard estilo terminal** (inspiração visual: `gaahzx/jarvis`, mas com muito mais conteúdo, porque tem muito mais sistema embaixo). Express servindo SPA estática em `public/`, HTML+CSS+JS vanilla, comunicação por REST + WebSocket com o backend Python já existente.

A F11 **não** é app mobile, **não** é PWA, **não** é React/Vue/framework. É vanilla por design: zero build step, edita o arquivo e recarrega.

A F11 **não** muda nenhuma lógica de negócio. Ela só **lê** o estado do agente e **dispara** missões/aprovações via endpoints que já existem ou que vão ser expostos como wrappers finos.

A F11 **não** substitui o Telegram. Telegram continua sendo o canal de aprovação em mobilidade. O painel é estação de trabalho.

---

## 2. Objetivos

1. SPA estática servida pelo próprio backend Python (FastAPI/aiohttp — o que já estiver no projeto), em `127.0.0.1:8080` por padrão, loopback-only igual `/health` da F10.
2. Painel único com 8 áreas lado a lado, layout grid, estilo terminal (monoespaçada, fundo escuro, verde/âmbar de destaque, sem framework CSS):
   - **Chat** — input + stream de resposta do agente (WebSocket).
   - **Missões** — ativas, pausadas, concluídas (filtro), com link pro trace.
   - **Skills** — todas (F3 manuais + F9 auto-geradas), com origem, tier, score do Crítico, contador de uso.
   - **Memória** — busca semântica na memória vetorial (Postgres pgvector ou bytea+cosine, o que tiver da F9), com top-K results e similaridade.
   - **Traces** — filtráveis por missão/tier/status, com timeline expandível por step.
   - **Crítico** — fila de decisões pendentes, aprovadas, rejeitadas, com o veredito dos 3 personas (técnico, advogado-do-diabo, sintetizador).
   - **Subagentes** — health dos workers, fila, latência, contagem de erros.
   - **Aprovações** — pendentes vindas do Telegram (mostra contexto e botão "aprovar/rejeitar" que dispara mesmo callback).
3. Métricas de evolução no topo: skills criadas (7d/30d), missões concluídas, taxa de aprovação do Crítico, uptime do serviço, tempo médio por tier (INSTANT/FAST/STRATEGIC/EPIC).
4. WebSocket único multiplexado por tópico (`chat`, `traces`, `health`, `approvals`) — não abrir um WS por painel.
5. Autenticação simples: token estático no arquivo `~/.agent/web_token` (chmod 600), enviado em header `X-Agent-Token`. Sem auth = 401. Sem TLS (loopback only).
6. Zero build step. Zero npm. Zero bundler. CSS num arquivo só, JS em módulos ES nativos (`<script type="module">`). Se precisar de algo tipo gráfico, usa Chart.js ou ApexCharts via CDN com SRI hash.
7. CLI `agent web` cobrindo start/stop/status/token-rotate.
8. Smoke test pós-build: painel sobe, todos os 8 painéis populam dados reais, chat responde, busca semântica retorna resultados, aprovação via UI dispara mesmo handler do Telegram.

---

## 3. Não-objetivos (NÃO fazer na F11)

- **Multi-usuário / contas / RBAC**: é uma máquina, um operador.
- **Edição de skills pelo navegador**: só visualização. Edição continua sendo no filesystem + Crítico.
- **Disparo de comandos arbitrários do sistema**: o chat fala com o orchestrator, não vira terminal SSH.
- **Mobile responsivo bonito**: funciona em mobile, mas o alvo é desktop 1440p+. Não vai ter media queries elaboradas.
- **Internacionalização**: PT-BR hardcoded.
- **Tema claro**: dashboard terminal é escuro, ponto.
- **Notificações push do navegador**: usa Telegram pra isso.
- **Histórico de chat compartilhado entre abas**: cada aba é uma sessão.
- **OAuth / SSO**: token estático resolve.
- **Server-side rendering**: SPA estática, fim.

---

## 4. Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Chrome/Firefox desktop, localhost:8080)           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  public/index.html   (entry, grid de 8 painéis)       │  │
│  │  public/css/term.css (tema terminal, único arquivo)   │  │
│  │  public/js/app.js    (boot + roteamento de WS)        │  │
│  │  public/js/panels/   (8 módulos ES, um por painel)    │  │
│  │  public/js/api.js    (fetch + WS client)              │  │
│  └───────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │  HTTP + WS
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  agent/web/server.py    (FastAPI ou aiohttp, já existente)  │
│  ├── routes/static.py    (serve public/ com cache headers)  │
│  ├── routes/api.py       (REST: /api/v1/{missions,skills,…})│
│  ├── routes/ws.py        (WS multiplexado por tópico)       │
│  ├── auth.py             (middleware X-Agent-Token)         │
│  └── adapters/                                              │
│       ├── orchestrator.py  (wrapper fino p/ F0–F4)          │
│       ├── missions.py      (wrapper p/ F5)                  │
│       ├── critic.py        (wrapper p/ F7)                  │
│       ├── skills.py        (wrapper p/ F3 + F9)             │
│       ├── memory.py        (wrapper p/ memória vetorial)    │
│       ├── traces.py        (wrapper p/ traces estruturados) │
│       ├── subagents.py     (wrapper p/ SubagentPool)        │
│       └── approvals.py     (wrapper p/ fila Telegram)       │
└─────────────────────────────────────────────────────────────┘
```

**Princípio:** adapter fino. Cada `adapters/*.py` é leitura + dispatch, não lógica. Toda regra de negócio fica nos módulos das fases anteriores. Se o painel quer algo que o backend não sabe responder, **adiciona método no módulo da fase certa**, não no adapter.

---

## 5. Componentes

### 5.1 Backend — `agent/web/server.py`

- App único (`FastAPI` se já tiver fastapi no projeto, senão `aiohttp` — não introduzir uma nova).
- Roda no mesmo processo do agente (anexado ao mesmo event loop), bind em `127.0.0.1:8080`.
- Middleware de auth: lê `X-Agent-Token`, compara com `~/.agent/web_token` (hash sha256). 401 se faltar/errado. Exceção: `/health` da F10 continua pública (loopback).
- Rate limit simples in-memory: 60 req/s por endpoint, 429 acima disso. WebSocket fora do rate limit.
- CORS: origin `null` e `http://127.0.0.1:8080` apenas. Nada de `*`.
- Logs: cada request entra no log JSON da F10 com `request_id`, `path`, `latency_ms`, `status`.

### 5.2 REST — `agent/web/routes/api.py`

Endpoints (todos sob `/api/v1/`, todos GET salvo indicado):

| Path | Verbo | Retorna |
|------|-------|---------|
| `/missions` | GET | lista paginada (filtro `status`, `tier`, `since`) |
| `/missions/{id}` | GET | detalhe + reflexão final |
| `/missions` | POST | cria missão nova (`{title, prompt, tier?}`) |
| `/missions/{id}/pause` | POST | pausa |
| `/missions/{id}/resume` | POST | retoma |
| `/skills` | GET | lista com origem (`manual`/`voyager`), uses, score |
| `/skills/{name}` | GET | metadados + último diff aprovado |
| `/skills/{name}/disable` | POST | marca como inactive |
| `/memory/search` | POST | `{query, k?, filter?}` → top-K com similaridade |
| `/traces` | GET | filtros: `mission_id`, `tier`, `status`, `since` |
| `/traces/{id}` | GET | árvore de steps |
| `/critic/queue` | GET | decisões pendentes |
| `/critic/history` | GET | aprovadas/rejeitadas, paginado |
| `/subagents` | GET | health snapshot |
| `/approvals` | GET | pendentes |
| `/approvals/{id}` | POST | `{decision: approve\|reject, note?}` |
| `/metrics/summary` | GET | números do topo do painel |
| `/system/info` | GET | versão, uptime, branch, tag, fase corrente |

Cada endpoint tem **timeout duro de 2s** (consulta a DB) ou **5s** (busca semântica). Acima disso → 504.

### 5.3 WebSocket — `agent/web/routes/ws.py`

Único endpoint: `WS /api/v1/stream?token=...`.

Mensagens cliente → servidor:
```json
{"op": "subscribe", "topic": "chat"}
{"op": "unsubscribe", "topic": "traces"}
{"op": "chat.send", "text": "..."}
```

Mensagens servidor → cliente:
```json
{"topic": "chat", "type": "token", "data": "..."}
{"topic": "chat", "type": "done", "data": {...}}
{"topic": "traces", "type": "step", "data": {...}}
{"topic": "health", "type": "snapshot", "data": {...}}
{"topic": "approvals", "type": "new", "data": {...}}
```

Heartbeat: ping a cada 20s, fecha se 3 pings sem pong. Backpressure: se o cliente acumular >100 mensagens não lidas, derruba a conexão e força reconnect.

### 5.4 Frontend — `public/`

```
public/
├── index.html         # grid 4×2 dos painéis + barra de métricas no topo
├── css/
│   └── term.css       # único CSS, tema terminal (verde #00ff9c, âmbar #ffb000, fundo #0a0e0a)
├── js/
│   ├── app.js         # boot, WS, roteamento de tópicos
│   ├── api.js         # fetch wrapper com X-Agent-Token automático
│   ├── ws.js          # cliente WS multiplexado
│   └── panels/
│       ├── chat.js
│       ├── missions.js
│       ├── skills.js
│       ├── memory.js
│       ├── traces.js
│       ├── critic.js
│       ├── subagents.js
│       └── approvals.js
└── assets/
    └── favicon.svg    # quadradinho verde minimalista
```

**Regras de front:**
- ES Modules nativos (`<script type="module">`), nada de require/bundler.
- Estado local em cada painel, **sem** store global (Redux, etc).
- Sem dependência externa salvo: Chart.js (sparklines no topo) e prismjs (highlight no painel de traces). Ambos via CDN com `integrity=sha384-...` no `<script>`.
- Fonte: `JetBrains Mono` ou `Fira Code` via CSS local em `assets/fonts/` (não baixa da net — F11 funciona offline).
- Layout grid CSS, sem flex acrobático. 8 painéis = grid 4 colunas × 2 linhas em 1440p+, colapsa pra 2×4 em <1280px, empilha vertical em <768px (mas sem polish).

### 5.5 CLI — `agent web`

Subcomandos:

```
agent web start                # sobe (já sobe junto com o serviço da F10, mas dá pra subir solto)
agent web stop                 # para
agent web status               # mostra bind, conexões ativas, último request
agent web token-rotate         # gera novo token, escreve em ~/.agent/web_token, invalida o antigo
agent web token-show           # imprime o token atual (só se TTY interativo)
agent web open                 # abre http://127.0.0.1:8080?token=... no browser padrão
```

`agent web open` é açúcar pra não ter que copiar token toda hora.

### 5.6 Storage

Nada novo. F11 só **lê** das tabelas já existentes (F3–F9) e usa adapters. Única tabela nova:

- `web_sessions` — registra abertura de sessão pra audit log (id, token_hash, opened_at, last_seen_at, ip, ua). Não armazena conteúdo do chat (chat é stateless por sessão de browser).

Migration: `011_web.sql`, idempotente.

---

## 6. Schema (migration `011_web.sql`)

```sql
CREATE TABLE IF NOT EXISTS web_sessions (
    id           BIGSERIAL PRIMARY KEY,
    token_hash   TEXT      NOT NULL,
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip           INET      NOT NULL,
    user_agent   TEXT      NOT NULL,
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_sessions_open
    ON web_sessions (last_seen_at)
    WHERE closed_at IS NULL;
```

---

## 7. Segurança

- Loopback only. Bind em `127.0.0.1`, **nunca** `0.0.0.0`. Verificado por teste (C7).
- Token de 32 bytes, base64url, gerado com `secrets.token_urlsafe(32)`.
- Comparação de token: `hmac.compare_digest`.
- CSP rígido no `index.html`:
  ```
  default-src 'self';
  script-src 'self' 'sha384-...' https://cdnjs.cloudflare.com;
  style-src 'self' 'unsafe-inline';
  connect-src 'self' ws://127.0.0.1:8080;
  img-src 'self' data:;
  font-src 'self';
  ```
- Sem cookies. Tudo em header `X-Agent-Token` (e query param `?token=` só pro WS, porque headers no WS dependem de extension).
- Sanitização de chat: o que o usuário digita vai pro orchestrator como texto puro, nunca renderizado como HTML no painel sem `textContent`. **Zero `innerHTML` em conteúdo dinâmico.** Lint do front grep contra isso.
- Sem upload de arquivo no painel. Quer mandar arquivo? CLI.

---

## 8. Performance e limites

- Build do front: 0s (não tem build).
- Cold load do `index.html` + assets: <500ms em rede local.
- Atualização WS de painel: <100ms p95.
- Tamanho total dos assets servidos: <300KB (sem CDN), <1MB (com fontes locais).
- Painel de traces aguenta missão com até 500 steps sem travar (virtualiza renderização).
- Painel de memória: busca semântica retorna em <500ms p95 (já vem do limite da F9).

---

## 9. Observabilidade (estende F10)

Métricas Prometheus novas (sob `/metrics` da F10, namespace `agent_web_`):

- `agent_web_http_requests_total{path,status}` counter
- `agent_web_http_request_duration_seconds{path}` histogram
- `agent_web_ws_connections_active` gauge
- `agent_web_ws_messages_total{topic,direction}` counter
- `agent_web_sessions_active` gauge
- `agent_web_chat_messages_total` counter
- `agent_web_chat_response_latency_seconds` histogram

Logs: todo request já entra no JSON da F10. Acrescentar campo `session_id` quando autenticado.

---

## 10. Critérios de aceitação

| ID | Critério | Como valida |
|----|----------|-------------|
| C1 | Backend roda no mesmo processo do serviço da F10 e responde em 127.0.0.1:8080 | `curl -H "X-Agent-Token: $TOKEN" http://127.0.0.1:8080/api/v1/system/info` retorna 200 |
| C2 | Sem token → 401 em todo `/api/v1/*` exceto `/health` | curl sem header → 401 |
| C3 | Bind nunca em 0.0.0.0 | `ss -tlnp` mostra só 127.0.0.1, teste automatizado verifica config |
| C4 | Os 8 painéis carregam dados reais do agente | smoke test E2E com Playwright headless |
| C5 | WebSocket multiplexado funciona (chat + traces simultâneos numa conexão) | teste de integração com cliente WS Python |
| C6 | Aprovação via UI dispara mesmo handler do Telegram | mock do handler verifica chamada idêntica |
| C7 | Zero `innerHTML` em conteúdo dinâmico do front | grep `-r "innerHTML" public/js/` retorna 0 matches |
| C8 | Heartbeat mata WS zumbi em <60s | teste com cliente que para de responder pong |
| C9 | Token rotacionado invalida sessões antigas em <5s | rotate + curl com token velho → 401 |
| C10 | Backend não introduz dependência Python nova além de FastAPI/aiohttp já existente + `websockets` se necessário | requirements diff revisado |
| C11 | Painel funciona 100% offline (sem CDN externa) | desconecta rede, recarrega, todos os painéis funcionam |
| C12 | Coverage dos módulos F11 ≥ 85% | `pytest --cov=agent/web` |

---

## 11. Plano de testes

```
tests/web/
├── test_auth.py              # C2, C9
├── test_bind.py              # C3
├── test_routes_missions.py   # C1, C4
├── test_routes_skills.py     # C4
├── test_routes_memory.py     # C4
├── test_routes_traces.py     # C4
├── test_routes_critic.py     # C4
├── test_routes_subagents.py  # C4
├── test_routes_approvals.py  # C4, C6
├── test_ws_multiplex.py      # C5
├── test_ws_heartbeat.py      # C8
├── test_rate_limit.py        # 429 acima de 60req/s
├── test_metrics.py           # endpoints prometheus aparecem
├── test_no_innerhtml.py      # C7 — lê arquivos de public/js/ e grep
├── test_csp.py               # CSP correto no HTML servido
└── e2e/
    └── test_smoke_panels.py  # C4 com Playwright headless (skip se Playwright não instalado)
```

Coverage gate no CI: 85% no `agent/web/`.

---

## 12. Anti-padrões (NÃO fazer)

- ❌ Trazer React/Vue/Svelte. Vai contra "edita e recarrega".
- ❌ Bundler (Vite/webpack/esbuild). Idem.
- ❌ Tailwind CDN. Já tô usando CSS, escrevo o que precisa.
- ❌ Local storage com chat history. Sessão de browser, fim.
- ❌ Cookie de sessão. Header X-Agent-Token.
- ❌ Endpoint que retorna lista sem paginação. Tudo paginado (default 50, max 200).
- ❌ Conexão WS direta a cada painel. UM WS multiplexado.
- ❌ `eval()` em qualquer lugar do front.
- ❌ `innerHTML` em conteúdo dinâmico. Use `textContent` ou cria nós com `document.createElement`.
- ❌ Adapter que faz lógica de negócio. Adapter é leitura + dispatch.
- ❌ Servir conteúdo do user-data direto pelo Express (XSS via filename, etc).
- ❌ Esconder erro de adapter mostrando "Indisponível" sem log. Mostra **e** loga.

---

## 13. Fora de escopo (NÃO fazer na F11)

- **Edição de skills pela UI**: F11.1 talvez.
- **Visualização gráfica de grafos de dependência de skills**: F11.2.
- **Mobile app nativo**: nunca, é PWA-able no futuro.
- **Compartilhamento de painel entre operadores**: single-user.
- **Replay de missões**: tem trace, suficiente. Replay é F12+.
- **Editor de prompts inline**: F13 (LoRA) talvez.

---

## 14. Entregáveis

- Branch `feature/phase-11-web-ui`
- Tag `phase-11-done` quando C1–C12 passarem
- Suite de testes: `tests/web/` cobrindo cada critério
- Smoke E2E com Playwright headless (skipável se libs não instaladas)
- Migration `011_web.sql` aplicada e idempotente
- CLI `agent web` documentado em `docs/web.md`
- Commit final: `feat(web): F11 - dashboard terminal-style com 8 painéis, WS multiplexado, auth por token`
- Nenhuma dependência Python nova além de `websockets` (se ainda não vier com FastAPI). Justifica.
- Nenhuma dependência JS no `package.json` — não existe `package.json` na F11.

---

## 15. Notas de operação (vão pro README/docs)

- Pra abrir o painel: `agent web open` (gera URL com token e abre o browser).
- Se rotacionou token e esqueceu, `agent web token-show` no TTY interativo.
- Painel é loopback only. Pra acessar de outra máquina na rede, SSH tunnel: `ssh -L 8080:127.0.0.1:8080 user@host`.
- O painel **não** é fonte de verdade. Tudo que ele mostra vive no Postgres + filesystem. Se quebrar, agente continua rodando.
- Painel quebrado não deve nunca derrubar o agente — adapter com defensive fallback, erro vira "indisponível" no painel + log estruturado.
- Não usa o painel pra debug de produção. Usa logs JSON da F10 + `agent deploy logs`.
- O chat do painel é uma sessão isolada. Não é o mesmo histórico do Telegram. Pra continuar conversa do Telegram, use o Telegram.
