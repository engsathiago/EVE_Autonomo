# agent-gateway

Gateway Node — traduz mensagens entre canais externos (Telegram, futuro: Discord/Slack) e o core Python.

## Arquitetura

```
Telegram ←→ bot.ts (Telegraf)
                ↓ HTTP
            core-client.ts → POST /v1/messages
                ↓ HTTP
            core-client.ts → POST /v1/approvals/{id}

Redis outbound:telegram → outbound/worker.ts → bot.telegram.sendMessage
```

## Env vars obrigatórias

| Var | Descrição | Exemplo |
|-----|-----------|---------|
| `TELEGRAM_BOT_TOKEN` | Token do bot do BotFather | `123456:ABC...` |
| `CORE_URL` | URL do core Python | `http://core:8000` |
| `REDIS_URL` | URL do Redis | `redis://redis:6379/0` |

## Env vars opcionais

| Var | Default | Descrição |
|-----|---------|-----------|
| `TELEGRAM_ALLOWED_CHAT_IDS` | `""` (aberto) | CSV de chat_ids autorizados |
| `PORT` | `3000` | Porta HTTP do gateway |
| `CORE_TIMEOUT_MS` | `30000` | Timeout para chamadas ao core (ms) |
| `CORE_RETRY_COUNT` | `3` | Tentativas em caso de falha de infra |

## Rodar local (dev)

```bash
# Instalar dependências
npm install

# Dev mode (hot reload)
TELEGRAM_BOT_TOKEN=xxx CORE_URL=http://localhost:8000 REDIS_URL=redis://localhost:6379/0 npm run dev
```

## Rodar via Docker Compose

```bash
# Sobe tudo: postgres, redis, core, gateway
docker compose up -d

# Ver saúde do gateway
curl localhost:3000/health
# → {"status":"ok","core":"reachable","redis":"reachable"}

# Ver logs do gateway
docker compose logs -f gateway
```

## Configurar bot Telegram (uma vez)

1. Abra o Telegram → `@BotFather` → `/newbot`
2. Anote o token
3. Mande `/start` pro seu bot e pegue seu `chat_id`:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[0].message.chat.id'
   ```
4. No `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_ALLOWED_CHAT_IDS=<seu_chat_id>
   ```

## Testes

```bash
npm test
```

## Estrutura

```
src/
├── index.ts              # Entry point
├── config.ts             # Loader de env (Zod)
├── core-client.ts        # HTTP client para o core (axios + retry)
├── health.ts             # GET /health
├── auth/
│   └── allowlist.ts      # Filtra chat_ids autorizados
├── channels/telegram/
│   ├── bot.ts            # Handlers text + callback_query
│   ├── keyboards.ts      # InlineKeyboard builders
│   └── formatters.ts     # Formatação de texto
└── outbound/
    ├── worker.ts         # BRPOP loop (despacha mensagens do Redis)
    └── router.ts         # Roteia OutboundMessage para canal correto
```

## Troubleshooting

**Gateway não sobe**: verificar `TELEGRAM_BOT_TOKEN` definido e core healthy (`docker compose ps`).

**Bot não responde**: confirmar que o `chat_id` está em `TELEGRAM_ALLOWED_CHAT_IDS` (ou que a var está vazia para modo aberto).

**Health retorna 503**: um dos serviços (core ou Redis) está unreachable — `docker compose logs core`.
