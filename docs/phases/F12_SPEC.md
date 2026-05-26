# F12 — Canais Extras (Discord + Slack + Email)

> Fase 12 do agente autônomo. Pré-requisito: F11 fechada na tag `phase-11-done`, com Web UI no ar, autenticação por token, WebSocket multiplexado e os 8 painéis carregando dados reais.

---

## 1. Contexto

Hoje o agente fala com o operador por:

- **CLI** (terminal local, F0–F8)
- **Telegram** (F3, aprovações em mobilidade)
- **Web UI** (F11, painel estação de trabalho)

Falta o resto do mundo. A F12 adiciona três canais extras, sem inventar nada e **sem repetir lógica de negócio**:

1. **Discord** — para conversas em servidor (comunidades, projetos paralelos, times pequenos)
2. **Slack** — para integração com workspace de trabalho (canais, threads, menções)
3. **Email** — para entrega assíncrona de relatórios, missões longas e digests do Crítico

A F12 reutiliza o **gateway multi-canal** que já existe em forma básica nas memórias do projeto antigo (eve.ia, com `MultiChannelRouter`), mas **não copia código**. O agente atual tem orquestrador, missões persistentes, Crítico, sandbox e aprovações — os canais novos são apenas **adaptadores finos** que falam com essas estruturas existentes.

A F12 **não** muda o orquestrador, **não** muda o Crítico, **não** muda as missões, **não** muda a sandbox. Ela só adiciona transportes.

A F12 **não** é multi-tenant. Cada instância do agente atende **um** servidor Discord, **um** workspace Slack, **um** mailbox. Configuração via `.env`.

A F12 **não** substitui o Telegram. Telegram continua sendo o canal de aprovação primário em mobilidade. Discord/Slack são canais de **conversa e disparo de missões**. Email é canal de **entrega**.

---

## 2. Objetivos

1. Adicionar três adaptadores de canal (Discord, Slack, Email) com a mesma interface dos canais existentes.
2. Unificar a interface por trás de um `ChannelAdapter` abstrato que CLI/Telegram/Web/Discord/Slack/Email implementam.
3. Roteamento por **canal de origem**: mensagem que entrou pelo Discord recebe resposta pelo Discord, missão concluída por mensagem do Discord notifica no Discord. Sem cross-channel automático.
4. Aprovações de irreversível (Crítico) podem vir por **qualquer** canal autenticado — mas o operador define no `.env` quais canais aceitam aprovação (`APPROVAL_CHANNELS=telegram,web`).
5. Rate limiting por canal e por usuário, para o agente não virar bot abusivo nem ser banido das plataformas.
6. Allowlist de usuários por canal — Discord por `user_id`, Slack por `member_id`, Email por endereço — para que o agente só responda a quem o operador autoriza.
7. Métricas Prometheus dos novos canais sob `/metrics` da F10 (namespace `agent_channel_*`).
8. Modo "canal desligado" via `.env`: se faltar token de uma plataforma, o adaptador nem inicializa e o sistema sobe normal.

---

## 3. Não-objetivos

- ❌ WhatsApp (custo de Business API, complexidade de aprovação Meta, fica fora desta fase).
- ❌ SMS/Twilio (mesmo motivo, pouco valor pro caso de uso).
- ❌ Voz / TTS / STT (fase futura, não aqui).
- ❌ Comandos slash do Discord/Slack com auto-complete avançado. Só comandos texto simples + menção do bot.
- ❌ Bot público no Discord/Slack. Esses bots ficam em servidores/workspaces **privados** do operador. Sem listagem em diretório.
- ❌ Reescrever o `MultiChannelRouter` antigo. A interface nova é nativa do projeto atual.
- ❌ Suporte a anexos de imagem/áudio recebidos (texto-only nesta fase, anexos é F12.1 se virar prioridade).
- ❌ Múltiplos servidores Discord ou workspaces Slack simultâneos.

---

## 4. Arquitetura

### 4.1 Interface comum: `ChannelAdapter`

Novo módulo `agent/channels/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class IncomingMessage:
    channel: str           # "discord" | "slack" | "email" | "telegram" | "cli" | "web"
    user_id: str           # id estável da plataforma
    user_display: str      # @handle ou nome
    text: str              # corpo da mensagem
    thread_id: Optional[str] = None   # id de thread (Slack) / reply (Discord) / message-id (Email)
    raw: Optional[dict] = None        # payload original, para debug

@dataclass
class OutgoingMessage:
    text: str
    thread_id: Optional[str] = None
    mission_id: Optional[str] = None  # se for resposta vinculada a missão
    is_approval: bool = False         # se é pedido de aprovação do Crítico

class ChannelAdapter(ABC):
    name: str  # "discord" | "slack" | "email"

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, user_id: str, msg: OutgoingMessage) -> None: ...

    @abstractmethod
    async def is_authorized(self, user_id: str) -> bool: ...
```

Os adaptadores **não** chamam o LLM nem o orquestrador direto. Eles entregam `IncomingMessage` ao `ChannelRouter`, que conhece o orquestrador.

### 4.2 `ChannelRouter`

`agent/channels/router.py`. Único ponto de entrada para mensagens externas. Responsabilidades:

1. Receber `IncomingMessage` de qualquer adaptador.
2. Aplicar allowlist (rejeita se `user_id` não autorizado para aquele canal).
3. Aplicar rate limit por (canal, user_id) — token bucket.
4. Resolver se a mensagem é:
   - **Comando** (começa com `/` ou menciona o bot e contém verbo de comando) → dispara missão no orquestrador
   - **Aprovação** (se canal está em `APPROVAL_CHANNELS` e mensagem casa com pendência ativa do Crítico) → handler de aprovação
   - **Chat livre** → resposta direta do agente (mesmo caminho do chat da F11)
5. Anexar `session_id = f"{channel}:{user_id}"` em todo trace para correlacionar logs.
6. Quando o orquestrador/Crítico/missão produz resposta, chama `adapter.send()` no canal de origem.

### 4.3 Adaptadores

```
agent/channels/
├── base.py
├── router.py
├── discord_adapter.py     # discord.py >= 2.3
├── slack_adapter.py       # slack-bolt async
└── email_adapter.py       # IMAP IDLE pra receber + SMTP pra enviar
```

#### Discord (`discord_adapter.py`)

- Lib: `discord.py` (oficial, manutenção ativa).
- Conecta com `DISCORD_BOT_TOKEN`, restrito a `DISCORD_GUILD_ID`.
- Escuta `on_message` e `on_thread_message`.
- Responde se: mencionado direto (`<@bot_id>`) **ou** mensagem em DM **ou** mensagem em canal listado em `DISCORD_CHANNELS`.
- Threading: cria thread no canal pra cada missão longa (>30s estimada). Resposta da missão volta na thread.
- Allowlist: `DISCORD_USER_ALLOWLIST` (lista de user_ids).
- Embeds: respostas com markdown viram embeds quando texto > 200 chars.

#### Slack (`slack_adapter.py`)

- Lib: `slack-bolt` (async) + `slack-sdk`.
- Modo **Socket Mode** (sem ngrok, sem porta aberta — Slack abre WS).
- Conecta com `SLACK_APP_TOKEN` (xapp-) e `SLACK_BOT_TOKEN` (xoxb-).
- Escuta `app_mention` e `message.im` (DMs).
- Threading: responde sempre na thread da mensagem original (`thread_ts`).
- Allowlist: `SLACK_USER_ALLOWLIST` (lista de member_ids).
- Blocks Kit: respostas longas usam blocos formatados, não texto plano.

#### Email (`email_adapter.py`)

- Recepção: **IMAP IDLE** (push, não polling) via `aioimaplib`.
- Envio: SMTP via `aiosmtplib`.
- Config: `EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`, `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_USER`, `EMAIL_PASS` (app password — nada de OAuth nesta fase).
- Allowlist: `EMAIL_FROM_ALLOWLIST` (lista de endereços; rejeita silenciosamente — não responde a desconhecido, pra não ser usado em reflexão de spam).
- Subject convention:
  - `[agent] <texto>` → comando/chat
  - `[agent] re: mission <id>` → mensagem vinculada a missão
- Body: texto plano. HTML é stripado na entrada. Saída sempre texto plano + assinatura `-- agent`.
- Reply: usa `In-Reply-To` e `References` corretos para manter thread no cliente de email.
- Anti-loop: nunca responde a email com header `Auto-Submitted: auto-replied` ou `X-Autoreply: yes`. Próprias respostas incluem `Auto-Submitted: auto-generated`.

### 4.4 Inicialização

`agent/channels/__init__.py` expõe `bootstrap_channels(config)` chamada do entrypoint principal. Lê `.env`:

```
CHANNELS_ENABLED=discord,slack,email     # opt-in explícito
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
DISCORD_USER_ALLOWLIST=111,222
DISCORD_CHANNELS=general,agent-control
SLACK_APP_TOKEN=...
SLACK_BOT_TOKEN=...
SLACK_USER_ALLOWLIST=U111,U222
EMAIL_IMAP_HOST=...
EMAIL_IMAP_PORT=993
EMAIL_SMTP_HOST=...
EMAIL_SMTP_PORT=587
EMAIL_USER=agent@...
EMAIL_PASS=...
EMAIL_FROM_ALLOWLIST=thiago@...,...
APPROVAL_CHANNELS=telegram,web          # quais canais podem aprovar irreversível
RATE_LIMIT_PER_USER_PER_MIN=20
RATE_LIMIT_PER_CHANNEL_PER_MIN=120
```

Se uma plataforma estiver faltando token, o `bootstrap_channels` loga `WARN channel=X disabled reason=missing_token` e segue.

### 4.5 Modelo de dados

Migração nova `db/migrations/012_channel_messages.sql`:

```sql
CREATE TABLE IF NOT EXISTS channel_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('in','out')),
    user_id TEXT NOT NULL,
    user_display TEXT,
    text TEXT NOT NULL,
    thread_id TEXT,
    mission_id TEXT,
    session_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_channel_messages_channel ON channel_messages(channel, created_at DESC);
CREATE INDEX idx_channel_messages_mission ON channel_messages(mission_id);
CREATE INDEX idx_channel_messages_session ON channel_messages(session_id);
```

Toda mensagem in/out passa por aqui antes de qualquer processamento. Serve como auditoria e como input pra busca semântica (F9 indexa esta tabela junto com o resto).

---

## 5. Segurança

- **Allowlist obrigatória por canal.** Sem allowlist configurada, o adaptador **nem sobe** (não default-allow).
- **Rate limit em dois eixos**: por user_id (anti-abuso individual) e por canal (anti-storm da plataforma).
- **Tokens nunca logados.** Logger redacta qualquer string que combine `^xox[abp]-`, `^[A-Za-z0-9]{50,}$` em headers.
- **Email anti-spoof**: valida SPF/DKIM via header `Authentication-Results` se presente. Se header diz `fail`, rejeita silenciosamente.
- **Discord/Slack anti-impersonation**: confia só em `user.id` da plataforma, **nunca** em display name.
- **Aprovação só em canal explicitamente autorizado** (`APPROVAL_CHANNELS`). Discord/Slack **não** aprovam irreversível por padrão — operador precisa ativar com consciência.
- **Painel de aprovação da F11 fica autoritativo.** Discord/Slack/Email podem **mostrar** que existe pendência, mas a F11/Telegram é quem aprova (default).
- **No-PII em logs do canal**. Logs registram `user_id`, não nome real nem email completo (email vai mascarado: `t***o@gmail.com`).

---

## 6. Comportamento

### 6.1 Comandos suportados (todos os canais)

| Comando | O que faz |
|---------|-----------|
| `/help` | Lista de comandos |
| `/status` | Status do agente: missões ativas, último heartbeat |
| `/mission <texto>` | Cria missão nova com `<texto>` como objetivo |
| `/missions` | Lista as missões ativas com IDs |
| `/mission <id>` | Detalhe de uma missão |
| `/cancel <id>` | Cancela missão (vai pro Crítico se irreversível em andamento) |
| `/skill <nome>` | Mostra info de uma skill |
| `/skills` | Lista skills disponíveis |
| `/approve <id>` | Aprova pendência do Crítico — **só funciona se canal em `APPROVAL_CHANNELS`** |
| `/deny <id>` | Nega pendência do Crítico — mesma restrição |

Mensagem sem `/` e sem menção do bot é tratada como **chat livre** (mesmo caminho do chat da F11): vai pro LLM com contexto de missões ativas + memória vetorial relevante, e a resposta volta no mesmo canal/thread.

### 6.2 Resposta em thread

- **Discord**: missão longa cria thread no canal de origem. Updates intermediários e resposta final na thread.
- **Slack**: sempre responde no `thread_ts` da mensagem original. Se mensagem original não tem thread, cria.
- **Email**: usa `In-Reply-To` da entrada. Missão longa pode enviar 2-3 emails de follow-up referenciando o mesmo thread.

### 6.3 Notificações proativas

O agente pode iniciar conversa (não só responder):

- **Crítico abre pendência** → notifica nos canais em `APPROVAL_CHANNELS` + canal de origem da missão.
- **Missão concluída** → notifica no canal de origem.
- **Reflexão diária** (se F10 cron configurado) → envia digest por email, se email habilitado.

### 6.4 Truncagem

- Resposta > 2000 chars no Discord vira embed.
- Resposta > 4000 chars no Slack vira arquivo `.txt` anexado.
- Email não trunca, mas se > 50 KB envia como `.txt` anexo + corpo curto.

---

## 7. Observabilidade

Métricas novas sob `/metrics` (namespace `agent_channel_`):

- `agent_channel_messages_total{channel,direction}` counter
- `agent_channel_message_latency_seconds{channel,direction}` histogram
- `agent_channel_rate_limited_total{channel,reason}` counter
- `agent_channel_unauthorized_total{channel}` counter
- `agent_channel_connection_status{channel}` gauge (0=down, 1=up)
- `agent_channel_missions_dispatched_total{channel}` counter

Logs JSON adicionam `channel`, `session_id`, `user_id_hash` (sha256 truncado, não user_id puro).

Health: `/health` da F10 inclui sub-status por canal: `{"discord":"up","slack":"up","email":"down:auth_failed"}`.

---

## 8. Critérios de aceitação

| ID | Critério | Como valida |
|----|----------|-------------|
| C1 | Sem token de uma plataforma, o resto sobe normal e log mostra `disabled` | inicia com só `EMAIL_*` setado, agente sobe, `/health` mostra discord/slack como `disabled` |
| C2 | Mensagem de user fora da allowlist é rejeitada e contabilizada | manda mensagem do user X fora da lista → não há resposta, `agent_channel_unauthorized_total{channel="discord"}` incrementa |
| C3 | Rate limit dispara em > N msgs/min do mesmo user | manda 25 msgs em 60s (limite 20), 5 são bloqueadas com aviso, metric `rate_limited_total` incrementa |
| C4 | Comando `/mission <texto>` cria missão idêntica à do CLI/Telegram | mock do orquestrador verifica `create_mission` chamado com mesmo payload independente do canal |
| C5 | Resposta sai pelo canal de origem | missão criada via Discord, resposta de conclusão chega no Discord; testar análogo Slack e Email |
| C6 | `/approve` só funciona em canais autorizados | tenta `/approve X` no Discord com `APPROVAL_CHANNELS=telegram,web` → resposta "não autorizado", pendência intacta |
| C7 | Threading correto | Discord: thread criada para missão longa. Slack: usa `thread_ts`. Email: usa `In-Reply-To` |
| C8 | Anti-loop de email | email com `Auto-Submitted: auto-replied` é descartado sem resposta |
| C9 | Email valida SPF/DKIM se header presente | mock de email com `Authentication-Results: ...; spf=fail; dkim=fail` é descartado |
| C10 | Tokens nunca aparecem em logs | grep nos logs após boot: nenhum token presente, apenas mascarado |
| C11 | `channel_messages` registra in e out | manda msg, verifica linha `direction=in`, recebe resposta, verifica linha `direction=out` |
| C12 | Métricas Prometheus expostas em `/metrics` | curl `/metrics` mostra todos os `agent_channel_*` |
| C13 | Coverage do módulo `agent/channels/` ≥ 85% | `pytest --cov=agent/channels` |
| C14 | Reuso real do orquestrador | grep no código: orquestrador não tem `if channel ==` em lugar nenhum, comportamento é igual pra todos |
| C15 | Bot Discord/Slack roda em servidor/workspace privado, sem entrar em diretório público | revisão manual da config do bot na plataforma |

---

## 9. Plano de testes

```
tests/channels/
├── test_base.py              # contrato do ChannelAdapter
├── test_router.py            # roteamento, allowlist, rate limit
├── test_discord_adapter.py   # mock de discord.py
├── test_slack_adapter.py     # mock de slack-bolt
├── test_email_adapter.py     # mock IMAP/SMTP
├── test_commands.py          # /mission, /status, etc, transversal
├── test_approval_gating.py   # C6
├── test_email_antispoof.py   # C8, C9
├── test_threading.py         # C7
├── test_persistence.py       # C11
├── test_metrics.py           # C12
├── test_secret_redaction.py  # C10
└── e2e/
    └── test_smoke_dispatch.py  # cria missão por cada canal mockado e checa resposta
```

Coverage gate no CI: 85% no `agent/channels/`.

---

## 10. Anti-padrões (NÃO fazer)

- ❌ **Copiar código do `multi_channel.py` antigo do eve-ia-github-ready.** Inspiração na arquitetura, sim. Cópia, não. O projeto atual tem outras estruturas (missões persistentes, Crítico, sandbox) que aquele código não conhece.
- ❌ **Default-allow.** Sem `*_USER_ALLOWLIST`, o adaptador não sobe. Período.
- ❌ **Polling de email.** IMAP IDLE ou nada. Polling vira custo de servidor e ruído nos logs.
- ❌ **Receber anexos.** Nesta fase, qualquer anexo é descartado com aviso ao remetente. Anexos pedem antivírus, sandbox, OCR — vira fase própria.
- ❌ **Comandos slash do Discord/Slack com registro de comandos.** Aumenta superfície de bug (registros pendentes, comandos fantasmas em servidor). Mensagem texto + menção resolve a v1.
- ❌ **OAuth para Gmail.** App password do `.env` por enquanto. OAuth + refresh token é fase futura se virar mainstream.
- ❌ **Banco compartilhado entre canais.** Cada `IncomingMessage` é uma linha em `channel_messages`. Sem cache de "estado do usuário" em RAM cross-canal.
- ❌ **Bot público.** Discord/Slack ficam restritos ao guild/workspace do operador.

---

## 11. Sequência de entrega

1. `base.py` + `router.py` + migração + testes do contrato (C14).
2. `email_adapter.py` (mais simples de testar, sem WebSocket de plataforma) + testes (C8, C9, C11).
3. `discord_adapter.py` + testes com mocks de `discord.py` (C7 Discord).
4. `slack_adapter.py` + testes com mocks de `slack-bolt` (C7 Slack).
5. `bootstrap_channels` + integração no entrypoint + `/health` por canal (C1).
6. Métricas Prometheus + redação de logs (C10, C12).
7. Gating de aprovação (C6) — toca handler do Crítico, **revisar com calma**.
8. E2E smoke por canal (mockados, não chama plataforma real).
9. Documentação `docs/channels.md` com como configurar cada um.
10. Tag `phase-12-done`.

---

## 12. Dependências novas

Adicionar em `requirements.txt`:

```
discord.py>=2.3.2
slack-bolt>=1.18.0
slack-sdk>=3.27.0
aioimaplib>=1.0.1
aiosmtplib>=3.0.1
email-validator>=2.1.0
```

Nada de framework de fila externa, nada de Celery, nada de Redis novo nesta fase. Tudo asyncio dentro do mesmo processo.

---

## 13. Riscos

| Risco | Mitigação |
|-------|-----------|
| Bot Discord/Slack banido por flood | Rate limit duplo (user + canal) + backoff em erro 429 da plataforma |
| Email vira vetor de prompt injection | Body é texto puro, comandos só por subject `[agent]`, allowlist estreita, sanitização de instruções suspeitas no body antes de mandar pro LLM |
| Aprovação acidental por canal errado | `APPROVAL_CHANNELS` default = `telegram,web`. Discord/Slack só com opt-in explícito do operador |
| Threading se perde em missão muito longa | `mission_id` registrado em `channel_messages` permite reconstrução mesmo se thread da plataforma quebrar |
| Mensagem perdida durante restart | F10 já tem persistência de missões; mensagens in/out gravadas em `channel_messages` antes do processamento — recuperação pós-reboot replica missões não concluídas |

---

## 14. Pós-F12

Próximas fases já no roadmap:

- **F13** — Local LoRA fine-tuning via Unsloth em Qwen/Llama, com gates de benchmark.
- **F14** — Experimentos RLAIF, contingente em estabilidade das fases anteriores.

F12.1 (se virar prioridade depois): anexos (imagem/áudio) e OAuth pro email.
