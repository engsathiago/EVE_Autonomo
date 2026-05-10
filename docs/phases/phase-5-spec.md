# Fase 5 — Gateway Node + Telegram

> Pré-requisito: Fases 1-4 concluídas e validadas.
> Objetivo: dar ao agente um canal de entrada/saída humano fora do CLI, começando por Telegram, com aprovação humana de skills e ações sensíveis.

---

## 1. Objetivo

Até a Fase 4, o agente só conversa via CLI (`agent chat`) ou HTTP direto no `core`. Não tem como o Thiago receber uma mensagem do agente no celular, nem responder do bar, nem aprovar uma ação que o agente quer executar.

A Fase 5 introduz o **Gateway Node** — um serviço separado, em TypeScript/Node.js, responsável por:

1. **Canais externos**: começa por Telegram (bot via long-polling). Arquitetura prevê adicionar WhatsApp, Slack, web widget depois.
2. **Aprovação humana**: skills marcadas como `requires_approval: true` no manifesto disparam mensagem inline com botões "Aprovar/Rejeitar" no Telegram antes de executar.
3. **Notificações proativas**: o agente pode enviar mensagem sem ter sido chamado (ex: "terminei a Fase X", "draft de skill nova esperando review", "erro na ingestão de podcast").
4. **Sessão por usuário**: cada chat_id do Telegram vira uma `session_id` no core, com histórico isolado.

O Gateway **não tem inteligência** — ele só traduz mensagens entre o canal externo e o core Python. Toda lógica de agente fica no core.

---

## 2. Arquitetura

### Por que Node separado e não Python?

- Bibliotecas de Telegram/WhatsApp/Slack são muito mais maduras em Node (telegraf, whatsapp-web.js, @slack/bolt).
- Queremos isolar I/O de canais (que tem websockets, long-polling, rate limits específicos) do core de raciocínio (que é CPU/LLM bound).
- Permite escalar independente: vários gateways (um por canal) falando com 1 core.

### Diagrama

```
┌──────────────────┐         ┌──────────────────┐
│   Telegram API   │◄───────►│  Gateway Node    │
│   (long-polling) │         │  (telegraf)      │
└──────────────────┘         └────────┬─────────┘
                                      │ HTTP
                                      │ (POST /v1/messages)
                                      ▼
                             ┌──────────────────┐
                             │   Core Python    │  ◄── (Fases 1-4)
                             │   (FastAPI)      │
                             └────────┬─────────┘
                                      │
                                      ├─ Postgres (sessions, skill_invocations, model_invocations)
                                      ├─ pgvector (memória)
                                      └─ Ollama / Anthropic / etc

         ┌──────────────────┐
         │  Redis (pub/sub) │  ◄── notificações proativas
         └──────────────────┘
                ▲
                │ core publica em "outbound:telegram"
                │ gateway assina e despacha
```

### Fluxos

**Fluxo 1 — Mensagem entrante (usuário → agente)**

1. Usuário envia mensagem no Telegram.
2. Gateway recebe via `bot.on('text')`.
3. Gateway chama `POST /v1/messages` no core, com `{session_id: "tg:<chat_id>", text: "...", channel: "telegram", user_id: "<tg_user_id>"}`.
4. Core processa (skill match, LLM call, etc).
5. Se a skill escolhida tem `requires_approval: true`, core retorna `{type: "approval_request", invocation_id, skill_name, args, summary}`.
6. Gateway envia mensagem com `InlineKeyboard` (botões Aprovar/Rejeitar).
7. Usuário clica → Gateway recebe `callback_query` → chama `POST /v1/approvals/<invocation_id>` com `{decision: "approve"|"reject"}`.
8. Core executa (ou descarta) e retorna resultado final.
9. Gateway envia resposta no chat.

**Fluxo 2 — Notificação proativa (agente → usuário)**

1. Algo no core gera evento (ex: nightly reflection encontrou padrão, skill foi promovida).
2. Core publica em Redis: `LPUSH outbound:telegram '{"chat_id": "...", "text": "...", "buttons": [...]}'`.
3. Gateway tem worker assinando `BRPOP outbound:telegram`.
4. Gateway envia via `bot.telegram.sendMessage(...)`.

**Fluxo 3 — Aprovação que expirou**

1. Approval fica pendente em `pending_approvals` (Postgres) com `expires_at` (default 30min).
2. Cron no core checa expirações → marca como `expired`, descarta a invocação.
3. Gateway recebe via Redis e edita a mensagem original removendo botões + texto "⏱ expirado".

---

## 3. Arquivos a criar/modificar

### Novos arquivos no core Python

| Arquivo | Responsabilidade |
|---|---|
| `core/src/agent/api/messages.py` | Endpoint `POST /v1/messages` (entrada de canais) |
| `core/src/agent/api/approvals.py` | Endpoints `POST /v1/approvals/<id>`, `GET /v1/approvals/<id>` |
| `core/src/agent/channels/__init__.py` | Re-exports |
| `core/src/agent/channels/base.py` | `Channel` enum, tipos canônicos `InboundMessage`, `OutboundMessage` |
| `core/src/agent/channels/dispatcher.py` | `OutboundDispatcher` — publica em Redis pra gateway consumir |
| `core/src/agent/approvals/manager.py` | `ApprovalManager` — cria, aprova, rejeita, expira |
| `core/src/agent/approvals/scheduler.py` | Cron que expira approvals (roda a cada 60s) |
| `core/src/agent/skills/manifest.py` | (modificar) ganha campo `requires_approval: bool = False` |
| `core/migrations/005_pending_approvals.sql` | Tabela `pending_approvals` + `outbound_messages_log` |
| `core/tests/api/test_messages.py` | Testes do endpoint /v1/messages |
| `core/tests/api/test_approvals.py` | Testes do fluxo de aprovação |
| `core/tests/approvals/test_manager.py` | Testes do ApprovalManager |
| `core/tests/approvals/test_expiration.py` | Testes do scheduler de expiração |

### Novos arquivos no Gateway Node

| Arquivo | Responsabilidade |
|---|---|
| `gateway/package.json` | Dependências Node |
| `gateway/tsconfig.json` | Config TS |
| `gateway/src/index.ts` | Entry — sobe bot Telegram + worker Redis |
| `gateway/src/config.ts` | Loader de env (TELEGRAM_BOT_TOKEN, CORE_URL, REDIS_URL, etc) |
| `gateway/src/core-client.ts` | Cliente HTTP do core (axios + retry) |
| `gateway/src/channels/telegram/bot.ts` | Bot telegraf — handlers de text, callback_query, /commands |
| `gateway/src/channels/telegram/keyboards.ts` | Builders de InlineKeyboard (approval, etc) |
| `gateway/src/channels/telegram/formatters.ts` | Formatação de respostas (markdown, escape, truncamento) |
| `gateway/src/outbound/worker.ts` | Worker Redis BRPOP que despacha pra canal correto |
| `gateway/src/outbound/router.ts` | Roteia OutboundMessage pro canal certo (só telegram nessa fase) |
| `gateway/src/auth/allowlist.ts` | Filtra chat_ids autorizados (só Thiago no MVP) |
| `gateway/src/health.ts` | Endpoint HTTP `/health` (pra docker healthcheck) |
| `gateway/src/types.ts` | Tipos compartilhados |
| `gateway/Dockerfile` | Build do gateway |
| `gateway/.dockerignore` | |
| `gateway/tests/core-client.test.ts` | Testes do cliente core (vitest + nock) |
| `gateway/tests/keyboards.test.ts` | Testes dos builders de teclado |
| `gateway/tests/auth.test.ts` | Testes de allowlist |
| `gateway/tests/outbound-worker.test.ts` | Testes do worker (mock Redis) |
| `gateway/README.md` | Como rodar local, env vars, troubleshooting |

### Arquivos a modificar

| Arquivo | Mudança |
|---|---|
| `core/src/agent/skills/schema.py` | Campo `requires_approval: bool` no `SkillManifest` |
| `core/src/agent/skills/runner.py` | Antes de executar skill com `requires_approval=True`, chama `ApprovalManager.create()` e retorna `ApprovalRequest` em vez de executar |
| `core/src/agent/server.py` | Registra `messages_router`, `approvals_router`. Inicia `ApprovalScheduler` no startup. |
| `core/src/agent/config.py` | Adiciona `RedisSettings`, `ApprovalsSettings` (timeout default, etc) |
| `core/pyproject.toml` | Adiciona `redis>=5.0` (já tem se a Fase 2 usou? confirma) |
| `core/skills/builtin/*/manifest.yaml` | Marca `requires_approval: true` em pelo menos 2 builtins (ex: `send_email`, se existir; ou cria `post_to_social` mock) |
| `docker-compose.yml` | Service novo `gateway`. Service `redis` se ainda não tem (Fase 2 já tem? confirma — se já tiver, reusa). |
| `cli/src/cli/main.py` | Subcomando `agent approvals list` (lista pendentes) |
| `CLAUDE.md` | Status Fase 5, padrão de canais, env vars novas |
| `.env.example` | TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS, GATEWAY_PORT |

---

## 4. Schema do banco

### Migration `005_pending_approvals.sql`

```sql
-- Tabela de approvals pendentes
CREATE TABLE IF NOT EXISTS pending_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    skill_args JSONB NOT NULL,
    summary TEXT NOT NULL,             -- texto humano-legível pra mostrar no canal
    channel TEXT NOT NULL,             -- "telegram" | "slack" | "cli" | etc
    channel_ref JSONB NOT NULL,        -- {chat_id: ..., message_id: ..., user_id: ...}
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    decided_by TEXT,                   -- user_id de quem decidiu
    decided_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_status_expires
    ON pending_approvals (status, expires_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pending_approvals_session
    ON pending_approvals (session_id, created_at DESC);

-- Log de mensagens outbound (audit trail)
CREATE TABLE IF NOT EXISTS outbound_messages_log (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT,
    channel TEXT NOT NULL,
    payload JSONB NOT NULL,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbound_log_undelivered
    ON outbound_messages_log (created_at)
    WHERE delivered = FALSE;
```

**Idempotência**: tudo `IF NOT EXISTS`. Pode rodar a migration 2x sem quebrar.

---

## 5. Interface

### Endpoints HTTP novos (core)

```
POST /v1/messages
  Body: {
    session_id: str,
    text: str,
    channel: "telegram" | "slack" | "cli",
    user_id: str,
    metadata: {...}  # opcional, ex: chat_id, message_id
  }
  Response (200): {
    type: "reply" | "approval_request",
    
    # Se type=reply:
    text?: str,
    
    # Se type=approval_request:
    approval_id?: str,
    skill_name?: str,
    summary?: str,
    expires_at?: ISO8601
  }

POST /v1/approvals/{approval_id}
  Body: { decision: "approve" | "reject", decided_by: str }
  Response (200): {
    status: "approved" | "rejected",
    result?: {...}  # se approved e a skill executou
  }

GET /v1/approvals/{approval_id}
  Response (200): { ...estado completo do approval }

GET /v1/approvals?status=pending&session_id=...
  Response (200): { items: [...], next_cursor: ... }
```

### Comando CLI novo

```
agent approvals list [--pending] [--session SESSION_ID]
agent approvals show APPROVAL_ID
agent approvals decide APPROVAL_ID approve|reject  # útil pra debug sem Telegram
```

### Variáveis de ambiente novas

```
# .env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321  # vírgula-separado
GATEWAY_PORT=3000
GATEWAY_CORE_URL=http://core:8000
GATEWAY_REDIS_URL=redis://redis:6379
APPROVAL_DEFAULT_TIMEOUT_SECONDS=1800  # 30min
```

---

## 6. Manifesto de skill com aprovação

Exemplo de skill que requer aprovação humana antes de executar:

```yaml
# core/skills/builtin/send_email/manifest.yaml
name: send_email
description: Envia email pra contato confirmado.
version: 1.0.0
requires_approval: true     # <── novo
approval_summary_template: | # <── novo, opcional
  📧 Enviar email para **{to}**
  Assunto: _{subject}_

  {body_preview}
preferred_models:
  - claude-haiku-4-5
arguments:
  type: object
  properties:
    to: {type: string, format: email}
    subject: {type: string}
    body: {type: string}
  required: [to, subject, body]
```

Quando o agente decide invocar `send_email`:

1. `SkillRunner` vê `requires_approval=true`.
2. Renderiza `approval_summary_template` com os args.
3. Cria registro em `pending_approvals`.
4. Retorna `ApprovalRequest` em vez de executar.
5. Endpoint `/v1/messages` propaga isso pro gateway.
6. Gateway desenha botões Aprovar/Rejeitar.
7. Quando usuário decide, `/v1/approvals/<id>` é chamado.
8. Se aprovado, `SkillRunner.execute_approved(approval_id)` roda a skill com os args originais.

---

## 7. Testes

### Core (Python)

| Arquivo | O que testa |
|---|---|
| `test_messages.py` | POST /v1/messages com canal "telegram" cria sessão tg:..., chama agente, retorna reply |
| `test_messages.py` | Mensagem que dispara skill com `requires_approval` retorna `type=approval_request` |
| `test_approvals.py` | POST /v1/approvals/{id} com `approve` executa skill e retorna resultado |
| `test_approvals.py` | POST /v1/approvals/{id} com `reject` marca como rejeitado, não executa |
| `test_approvals.py` | Approval expirado não pode mais ser aprovado (retorna 409) |
| `test_manager.py` | `ApprovalManager.create()` insere com `expires_at` correto |
| `test_manager.py` | `decide()` é idempotente — segunda chamada retorna estado atual sem mudar |
| `test_expiration.py` | Scheduler marca approvals com `expires_at < now()` como `expired` |
| `test_expiration.py` | Scheduler publica evento outbound pra notificar gateway de expiração |

Mínimo: 15 testes novos no core. Coverage da pasta `approvals/` ≥ 90%.

### Gateway (Node + Vitest)

| Arquivo | O que testa |
|---|---|
| `core-client.test.ts` | POST /v1/messages com retry em 503 |
| `core-client.test.ts` | Timeout de 30s no core retorna erro tratado |
| `keyboards.test.ts` | `buildApprovalKeyboard(approval_id)` gera markup correto |
| `auth.test.ts` | Chat_id fora da allowlist é rejeitado silenciosamente |
| `auth.test.ts` | Chat_id na allowlist passa |
| `outbound-worker.test.ts` | Mensagem em `outbound:telegram` dispara `bot.telegram.sendMessage` com payload correto |
| `outbound-worker.test.ts` | Erro do Telegram (rate limit) loga e re-enfileira com backoff |

Mínimo: 10 testes no gateway. Mock do Telegram via stub do `bot.telegram`.

### Integração end-to-end (manual, não automatizada nessa fase)

Lista no Passo 11 do guia operacional.

---

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Gateway com bug envia mesma mensagem 2x | Idempotency-key baseado em `(channel, channel_ref.message_id)`. Core dedup em 60s. |
| Telegram rate limit (30 msg/s global) | Worker outbound usa rate limiter (`bottleneck`). Filas de prioridade: approval > reply > notification. |
| Token do bot vaza no log | `config.ts` mascara tokens em todos os logs. Pre-commit hook checa `git diff` por padrões `[0-9]+:[A-Za-z0-9_-]{35}`. |
| Approval fica pendente pra sempre | Scheduler expira em 30min default. Configurável por skill. |
| Gateway cai e perde notificações outbound | Redis persiste (AOF). Mensagens não-entregues ficam em `outbound:telegram`. Quando gateway sobe, pega o backlog. |
| Core fica fora do ar e usuário manda msg | Gateway responde "estou processando..." e enfileira em `inbound_buffer:telegram`. Quando core volta, drena. |
| Usuário aprova ação que era injection | Allowlist de chat_ids. Skills sensíveis sempre `requires_approval=true`. Approval mostra os args reais, não só o nome. |
| Botão "Aprovar" clicado 2x em sequência | `decide()` é idempotente. Segundo clique retorna estado atual sem reexecutar. |
| Mensagens muito longas (>4096 char Telegram) | Formatter trunca + envia "..." com link pra chat completo (futuro: web view) |
| Gateway e core em Docker compose mas Telegram precisa internet | Service `gateway` tem `network_mode: bridge` (default). Sem `extra_hosts` específico. |

---

## 9. Critérios de aceitação

- [ ] `docker compose up -d` sobe `core`, `gateway`, `redis`, `postgres`, `ollama` (este último opcional).
- [ ] `docker compose ps` mostra `gateway` como `healthy`.
- [ ] `curl localhost:3000/health` retorna `{"status":"ok","core":"reachable","redis":"reachable"}`.
- [ ] Mandar mensagem pro bot no Telegram → recebe resposta do agente em <10s (modelo rápido).
- [ ] Mandar comando que dispara skill com `requires_approval` → recebe mensagem com botões Aprovar/Rejeitar.
- [ ] Clicar "Aprovar" → skill executa, resposta volta no chat.
- [ ] Clicar "Rejeitar" → bot responde "ok, ignorado", skill não executa.
- [ ] Aguardar 30min sem decidir → mensagem é editada pra "⏱ expirado", botões somem.
- [ ] `agent approvals list --pending` lista approvals em aberto.
- [ ] `agent approvals decide <id> approve` funciona via CLI (sem Telegram).
- [ ] Tabela `pending_approvals` tem registros com `status` correto após cada teste acima.
- [ ] Tabela `outbound_messages_log` tem linha pra cada mensagem enviada pelo gateway.
- [ ] Mensagem de chat_id fora da allowlist é ignorada silenciosamente (log no gateway, mas sem resposta).
- [ ] Reiniciar `gateway` no meio de um approval pendente → ao subir, approval continua válido e botões ainda funcionam.
- [ ] Todos os testes do passo 7 passam (`pytest` no core, `npm test` no gateway).
- [ ] Fases 1-4 continuam passando (`pytest` no core não quebrou nada).
- [ ] CLAUDE.md atualizado.

---

## 10. O que NÃO é Fase 5 (deixa pra depois)

- ❌ WhatsApp / Slack / web widget (Fase 6 expande canais).
- ❌ Voice input/output via Telegram (Fase 7).
- ❌ Aprovação delegada — "user A pode aprovar pelo user B" (Fase 9 — multi-tenant).
- ❌ Aprovação em lote — "aprovar todas as próximas 5 ações desse tipo" (Fase 8 — políticas).
- ❌ Markdown V2 completo do Telegram com formatação rica de tabelas, código (Fase 6).
- ❌ Web dashboard pra ver approvals pendentes via browser (Fase 10).
- ❌ Webhook do Telegram em vez de long-polling (Fase 6 — quando tiver domínio público).
- ❌ Auto-aprovar baseado em confiança histórica da skill (Fase 8 — reflexão).

Mantenha disciplina. Se o Claude Code propor mais que isso, recuse.

---

## 11. Configuração do bot Telegram (você faz manualmente antes do Passo 6 do guia)

1. Abre o Telegram, busca `@BotFather`.
2. `/newbot` → nome (ex: "Eve Agent (dev)") → username (ex: `eve_agent_dev_bot`, precisa terminar em `_bot`).
3. Anota o token (`123456:ABC...`).
4. `/setprivacy` → desabilita (pra bot ler todas as mensagens do chat se virar grupo no futuro).
5. Manda `/start` pro próprio bot. Pega seu `chat_id`:
   - `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` — procura `"chat":{"id":...}`.
6. Coloca no `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_ALLOWED_CHAT_IDS=<seu chat_id>
   ```

**Não comita o `.env` no git.** O `.env.example` tem só placeholders.

---

## 12. Estimativa

| Etapa | Tempo |
|---|---|
| Sessão Claude Code (implementação) | 4-6h |
| Você revisando + setup BotFather | 1h |
| Validação manual ponta-a-ponta | 1h |
| **Total wall-clock** | **~1 dia útil** |

Custo Anthropic estimado na sessão: $4-6 USD.

---

## 13. Estrutura de pastas resultante

```
agent/
├── core/                          # já existe (Fases 1-4)
│   ├── src/agent/
│   │   ├── api/
│   │   │   ├── messages.py       # NOVO
│   │   │   └── approvals.py      # NOVO
│   │   ├── approvals/             # NOVO
│   │   │   ├── manager.py
│   │   │   └── scheduler.py
│   │   ├── channels/              # NOVO
│   │   │   ├── base.py
│   │   │   └── dispatcher.py
│   │   └── skills/
│   │       └── schema.py          # MODIFICADO (campo requires_approval)
│   ├── migrations/
│   │   └── 005_pending_approvals.sql  # NOVO
│   └── tests/
│       ├── api/                   # NOVO
│       └── approvals/             # NOVO
│
├── gateway/                        # NOVO — todo o diretório
│   ├── src/
│   │   ├── index.ts
│   │   ├── config.ts
│   │   ├── core-client.ts
│   │   ├── channels/telegram/
│   │   │   ├── bot.ts
│   │   │   ├── keyboards.ts
│   │   │   └── formatters.ts
│   │   ├── outbound/
│   │   │   ├── worker.ts
│   │   │   └── router.ts
│   │   ├── auth/allowlist.ts
│   │   ├── health.ts
│   │   └── types.ts
│   ├── tests/
│   ├── package.json
│   ├── tsconfig.json
│   ├── Dockerfile
│   └── README.md
│
├── docker-compose.yml             # MODIFICADO (+ service gateway)
├── .env.example                   # MODIFICADO
└── CLAUDE.md                      # MODIFICADO
```
