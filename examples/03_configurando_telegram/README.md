# 03 — Configurando Telegram

Conecte a EVE ao Telegram em 5 minutos.

## 1. Crie um bot no Telegram

1. Abra o Telegram e procure **@BotFather**
2. Envie `/newbot`
3. Escolha um nome (ex: "Eve - Meu Agente")
4. Escolha um username (ex: `meu_eve_bot`)
5. Copie o **token** retornado (algo como `1234567890:ABC-DEF...`)

## 2. Descubra seu chat_id

1. Inicie uma conversa com seu bot recém-criado
2. Envie qualquer mensagem (ex: "oi")
3. Acesse no navegador:
   ```
   https://api.telegram.org/bot<SEU_TOKEN>/getUpdates
   ```
4. Procure pelo campo `"chat":{"id":...}` — esse é o seu `chat_id`

## 3. Configure o .env

Adicione ao seu `.env`:

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABC-DEF-seu-token-aqui
TELEGRAM_ALLOWED_CHAT_IDS=123456789   # Seu chat_id (CSV se múltiplos)
```

⚠️ **CRÍTICO:** Sempre defina `TELEGRAM_ALLOWED_CHAT_IDS`. Sem isso, qualquer pessoa que descobrir o username do bot pode conversar com a EVE.

## 4. Reinicie o Gateway

```bash
docker compose restart gateway
```

Verifique os logs:

```bash
docker compose logs -f gateway
# Deve mostrar: "Telegram bot started" e "allowlist: [123456789]"
```

## 5. Teste

No Telegram, envie para o bot:

```
Olá, EVE!
```

A EVE deve responder em segundos.

## Aprovações via Telegram

Quando o agente tentar executar uma operação sensível (ex: `rm` em algum arquivo), você receberá uma mensagem com botões inline:

```
🔐 Aprovação Necessária

Action: shell
Command: rm /tmp/old_logs.txt

[ ✅ Aprovar ] [ ❌ Negar ]
```

Toque no botão para autorizar ou negar.

## Comandos especiais

Envie para o bot:

| Comando | O que faz |
|---------|-----------|
| `/start` | Apresenta a EVE |
| `/help` | Lista comandos |
| `/status` | Mostra status do agente |
| `/approvals` | Lista aprovações pendentes |
| `/cancel` | Cancela operação em andamento |

## Múltiplos usuários autorizados

```bash
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321,555444333
```

Cada chat_id terá sua própria `conversation_id`, mantendo contextos separados.

## Troubleshooting

### Bot não responde
```bash
docker compose logs gateway | grep -i telegram
# Verifique se "Telegram bot started" aparece
# Se aparecer "Unauthorized chat_id", revise TELEGRAM_ALLOWED_CHAT_IDS
```

### Mensagens em Markdown vêm quebradas
O bot escapa caracteres especiais automaticamente. Se ver problemas, abra uma issue.

## Próximo passo

[04_missao_complexa](../04_missao_complexa/) — Use missões para tarefas multi-step.
