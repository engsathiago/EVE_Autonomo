# Canais Extras — Guia de Configuração (F12)

## Visão geral

A F12 adiciona três adaptadores Python que rodam **dentro do processo core** (não no gateway Node):

| Canal | Lib | Modo |
|-------|-----|------|
| Discord | discord.py ≥ 2.3 | WebSocket (gateway Discord) |
| Slack | slack-bolt async | Socket Mode (xapp-) |
| Email | aioimaplib + aiosmtplib | IMAP IDLE + SMTP |

O gateway Node continua servindo apenas Telegram.

### Ativação

```env
CHANNELS_ENABLED=discord,slack,email   # CSV opt-in. Vazio = nenhum canal sobe.
```

Canais não listados em `CHANNELS_ENABLED` são ignorados silenciosamente.
Se o token ou a allowlist obrigatória estiver ausente, o adapter loga `WARN` e **não sobe** — o agente continua funcionando nos demais canais.

---

## Discord

### 1. Criar o bot

1. Acesse [discord.com/developers/applications](https://discord.com/developers/applications) e crie uma Application.
2. Em **Bot**, gere um token e copie.
3. Em **OAuth2 → URL Generator**, marque scopes `bot` e permissions:
   - `Read Messages/View Channels`
   - `Send Messages`
   - `Create Public Threads`
4. Convide o bot **apenas para o seu servidor privado** usando a URL gerada.
5. Em **Bot**, habilite **Message Content Intent** (necessário para ler mensagens).

### 2. Variáveis

```env
DISCORD_BOT_TOKEN=MTx...          # Bot token
DISCORD_GUILD_ID=123456789        # ID do servidor (clique com botão direito → Copiar ID)
DISCORD_USER_ALLOWLIST=111,222    # IDs dos usuários autorizados (obrigatório)
DISCORD_CHANNELS=general,ops     # Nomes dos canais monitorados (opcional; DMs e menções sempre funcionam)
```

`DISCORD_USER_ALLOWLIST` é **obrigatório**. Sem ele, o adapter recusa inicializar.

### 3. Comportamento

- O bot responde a DMs e menções (`@bot`) em qualquer canal autorizado.
- Mensagens em canais não listados em `DISCORD_CHANNELS` (e que não sejam DM/menção) são ignoradas.
- Respostas ≤ 200 chars: texto puro. Respostas > 200 chars: Embed.
- Anexos são descartados com aviso. Mensagens de outros bots são ignoradas.

---

## Slack

### 1. Criar o app (Socket Mode)

1. Acesse [api.slack.com/apps](https://api.slack.com/apps) e crie um app **From scratch**.
2. Em **Socket Mode**, ative e gere um **App-Level Token** (`xapp-`) com scope `connections:write`.
3. Em **OAuth & Permissions**, adicione Bot Token Scopes:
   - `app_mentions:read`, `im:read`, `im:write`, `chat:write`, `files:write`
4. Em **Event Subscriptions**, ative e inscreva-se em:
   - `app_mention`, `message.im`
5. Instale o app no workspace e copie o **Bot User OAuth Token** (`xoxb-`).

### 2. Variáveis

```env
SLACK_APP_TOKEN=xapp-1-...        # App-Level Token (Socket Mode)
SLACK_BOT_TOKEN=xoxb-...          # Bot User OAuth Token
SLACK_USER_ALLOWLIST=U111,U222    # Member IDs autorizados (obrigatório)
```

`SLACK_USER_ALLOWLIST` é **obrigatório**. Sem ele, o adapter recusa inicializar.

### 3. Comportamento

- O bot responde a menções (`@bot`) em canais e DMs.
- Respostas ≤ 4000 chars: `chat_postMessage`. Respostas > 4000 chars: `files_upload_v2`.
- Threading: sempre usa `thread_ts` da mensagem original.
- Anexos e mensagens de outros bots são descartados.

---

## Email (IMAP IDLE + SMTP)

### 1. Configurar conta de email

**Gmail (recomendado):**

1. Crie uma conta dedicada para o agente (ex: `agente@gmail.com`).
2. Ative verificação em duas etapas na conta.
3. Em **Segurança → Senhas de app**, gere uma senha de app e copie.
4. Ative IMAP em **Configurações → Ver todos os ajustes → Encaminhamento e POP/IMAP**.

**Outros provedores:** qualquer conta com suporte a IMAP IDLE e SMTP com TLS.

### 2. Variáveis

```env
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USER=agente@gmail.com
EMAIL_PASS=xxxx xxxx xxxx xxxx    # App password (não a senha da conta)
EMAIL_FROM_ALLOWLIST=voce@empresa.com,colega@empresa.com
```

`EMAIL_FROM_ALLOWLIST` é **obrigatório**. Sem ele, o adapter recusa inicializar.

### 3. Protocolo de mensagens

- O agente só processa emails cujo remetente esteja em `EMAIL_FROM_ALLOWLIST`.
- Assunto deve começar com `[agent]` (ex: `[agent] resumir relatório`).
- O corpo do email é extraído como texto plano (HTML é convertido).
- Respostas são enviadas via SMTP com `In-Reply-To` e `References` para manter a thread.
- Emails com cabeçalho `Auto-Submitted` ou `X-Autoreply` são descartados (anti-loop).
- Emails com falha em SPF **e** DKIM (verificado via `Authentication-Results`) são descartados.
- Anexos são descartados com aviso no corpo da resposta.

---

## Gating de aprovação

Por padrão, apenas `telegram` e `web` podem executar `/approve` e `/deny`.

Para permitir que Discord, Slack ou Email aprovem ações irreversíveis:

```env
APPROVAL_CHANNELS=telegram,web,discord   # adicione com opt-in explícito
```

Sem essa configuração, `/approve` em canais não autorizados retorna mensagem de bloqueio.

---

## Rate limits

```env
RATE_LIMIT_PER_USER_PER_MIN=20      # máx. 20 mensagens por usuário por minuto
RATE_LIMIT_PER_CHANNEL_PER_MIN=120  # máx. 120 mensagens por canal por minuto
```

Usuários que excedem o limite recebem mensagem de aviso. A métrica `agent_channel_rate_limited_total` contabiliza os bloqueios.

---

## Métricas

Todas as métricas ficam no namespace `agent_channel_*` e são expostas em `/metrics`:

| Métrica | Tipo | Labels |
|---------|------|--------|
| `agent_channel_messages_total` | Counter | channel, direction |
| `agent_channel_message_latency_seconds` | Histogram | channel, direction |
| `agent_channel_rate_limited_total` | Counter | channel, reason |
| `agent_channel_unauthorized_total` | Counter | channel |
| `agent_channel_connection_status` | Gauge | channel |
| `agent_channel_missions_dispatched_total` | Counter | channel |

---

## Persistência

Toda mensagem (entrada e saída) é gravada na tabela `channel_messages` (migration `013_channel_messages.sql`):

```sql
SELECT channel, direction, user_display, text, created_at
FROM channel_messages
WHERE channel = 'discord'
ORDER BY created_at DESC
LIMIT 20;
```

---

## Segurança de logs

Tokens de plataforma nunca aparecem em logs. O processor `redact_secrets` (integrado ao structlog) redige automaticamente:
- Tokens Slack (`xoxb-`, `xoxp-`, `xoxa-`, `xapp-`)
- Qualquer string de 50+ caracteres alfanuméricos (tokens de API genéricos: Discord, OpenAI, etc.)

---

## Troubleshooting

| Sintoma | Causa provável | Solução |
|---------|---------------|---------|
| Adapter não sobe, log `WARN channels.config_error` | Token ou allowlist ausente | Verifique as variáveis de env |
| Discord não responde em canais | Canal não está em `DISCORD_CHANNELS` | Adicione o nome do canal à variável |
| Slack responde em thread errada | `thread_ts` incorreto no evento | Verifique o payload do evento; normalmente auto-resolvido |
| Email não processa mensagem | Assunto sem prefixo `[agent]` | Adicione `[agent]` no início do assunto |
| Email em loop | `Auto-Submitted` ausente na resposta | O adapter já define o header; verifique se outro sistema está removendo |
| SPF/DKIM fail legítimo | Provedor não assina corretamente | Configure DKIM/SPF no DNS do domínio de envio |
| `/approve` bloqueado em Discord | Canal não está em `APPROVAL_CHANNELS` | Adicione `discord` à variável `APPROVAL_CHANNELS` com opt-in explícito |
| `agent_channel_connection_status{channel="discord"} 0` | Bot desconectado | Verifique `DISCORD_BOT_TOKEN` e reconecte o bot |
