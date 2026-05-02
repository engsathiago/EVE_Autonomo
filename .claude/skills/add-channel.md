# Adicionar um Canal novo ao gateway

## Quando usar
Quando o usuário pedir conexão com Telegram/Discord/Slack/etc.

## Passos
1. Crie `gateway/src/channels/{nome}.ts`
2. Implemente interface `Channel` de `channels/base.ts`
3. Use a lib oficial do canal (telegraf, discord.js, baileys, etc.)
4. Conecte ao Redis bus via `bus/redis.ts`
5. Registre em `gateway/src/index.ts` no `setupChannels()`
6. Adicione config em `config/config.yaml` em `channels.{nome}`
7. Adicione vars em `.env.example`
8. Teste em `gateway/tests/channels/{nome}.test.ts`

## Padrão
Veja `channels/telegram.ts` como referência canônica.
