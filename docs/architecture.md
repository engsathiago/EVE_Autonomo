# Arquitetura — Agente Autônomo Híbrido

## 1. Princípios

1. **Funcional em todas as fases.** Cada fase entrega um agente que já roda.
2. **Separação clara Python/Node.** Python pensa, Node fala com o mundo.
3. **Plugável.** Tools, transports, canais, skills e sandboxes são todos
   carregados dinamicamente.
4. **Observável.** Cada decisão do agente vira um trace estruturado.
5. **Configurável sem código.** SOUL.md, AGENTS.md, TOOLS.md controlam
   comportamento.

## 2. Componentes

### 2.1 Core (Python)

#### AIAgent (`core/src/agent/core.py`)
Loop principal ReAct + reflection. Recebe um goal, executa N iterações
com tool calls, reflete a cada N passos, persiste memória ao final.

```
┌─────────┐
│  Goal   │
└────┬────┘
     ▼
┌──────────────┐
│ Plan + Act   │◄──── Transport (LLM)
└──────┬───────┘
       ▼
┌──────────────┐
│ Tool Execute │◄──── Tool Registry
└──────┬───────┘
       ▼
┌──────────────┐
│ Observe      │
└──────┬───────┘
       ▼
┌──────────────┐
│ Reflect (N)  │◄──── Sonnet
└──────┬───────┘
       ▼
   Continue or Done?
```

#### Transports (`transports/`)
Abstração sobre providers de LLM. Interface única:
```python
async def chat(system, messages, tools) -> {"text", "tool_calls", "raw"}
```
Implementações: Anthropic, OpenAI, OpenRouter, Ollama. Trocar provider = 1 linha
em config.yaml.

#### Memory (`memory/`)
- **`store.py`:** PostgreSQL com pgvector. Tabelas: `conversations`,
  `messages`, `memories`, `skills`, `jobs`.
- **`fts.py`:** Full-text search via tsvector.
- **`curator.py`:** Após cada conversa, decide o que persistir como memória
  durável. Roda em background.
- **`compressor.py`:** Quando contexto > 50% do limite, comprime mensagens
  antigas em sumário.

#### Skills (`skills/`)
Skill = arquivo markdown com frontmatter + corpo de instrução. Ex:
```markdown
---
name: backup-postgres
trigger: "fazer backup do postgres"
tools: [shell, filesystem]
---
1. Identificar o banco alvo
2. Rodar pg_dump
3. Comprimir e mover pra /backups/
```

`creator.py` observa tarefas com 5+ tool calls bem-sucedidas e propõe criar
skill nova. Usuário aprova → vira arquivo permanente.

#### Tools (`tools/`)
Cada tool: classe Python com `name`, `description`, `input_schema`,
`async execute()`. Registry carrega de `builtin/` + plugins externos.

#### Sandbox (`sandbox/`)
Interface comum pra executar código:
- **Local:** subprocess direto (rápido, inseguro)
- **Docker:** container efêmero (default)
- **SSH:** máquina remota dedicada

#### Scheduler (`scheduler/`)
APScheduler com persistência em Postgres. `cron.py` parseia linguagem natural
("toda terça às 9h") via LLM em cron expression.

#### Plugins (`plugins/`)
Loader varre `~/.agent/plugins/*.py` e registra automaticamente. API simples:
```python
from agent.plugins.api import register_tool, register_skill
```

### 2.2 Gateway (Node)

#### Server (`gateway/src/index.ts`)
Fastify expondo `/api/send` (Python pede pra mandar mensagem) e `/api/health`.
Subscreve canal Redis `agent:out:*` pra enviar respostas.

#### Channels (`gateway/src/channels/`)
Cada canal implementa interface comum:
```typescript
interface Channel {
  start(): Promise<void>;
  send(target: string, message: Message): Promise<void>;
  on(event: 'message', handler: (msg: IncomingMessage) => void): void;
}
```

Implementações iniciais:
- **Telegram:** telegraf
- **Discord:** discord.js
- **WhatsApp:** baileys (não-oficial)
- **Slack:** @slack/bolt
- **Signal:** signal-cli wrapper
- **Email:** nodemailer + IMAP

#### Bus (`gateway/src/bus/`)
- **redis.ts:** publica em `agent:in`, subscreve `agent:out:*`
- **core_client.ts:** HTTP client pro core Python

#### Approvals (`gateway/src/approvals.ts`)
Tools marcadas como `requires_confirmation` mandam pedido de aprovação pelo
canal antes de executar. Usuário responde "ok" ou "no".

### 2.3 Web UI

HTML/JS vanilla. Sem build, sem framework. Estilo `hermes-webui`:
- Painel esquerdo: sessões
- Centro: chat com SSE streaming
- Direito: workspace files
- Footer: model selector + token ring

### 2.4 CLI

`agent` comando único com subcomandos:
- `agent setup` — wizard interativo
- `agent run` — modo REPL
- `agent gateway start` — inicia gateway Node
- `agent skills list` — lista skills
- `agent jobs list` — lista cron jobs

## 3. Fluxo de uma mensagem

```
1. Usuário manda msg no Telegram
2. gateway/channels/telegram.ts recebe → publica em Redis `agent:in`
3. core/server.py subscriber recebe → chama AIAgent.run(message)
4. AIAgent loop:
   - Consulta memória relevante
   - Pede plano ao Anthropic transport (Haiku)
   - Executa tools necessárias
   - A cada 3 iter, pede reflexão (Sonnet)
   - Streama tokens via Redis `agent:stream:{id}`
5. Resposta final publicada em `agent:out:telegram:{chat_id}`
6. gateway recebe → telegram.ts envia mensagem
7. curator.py em background extrai memórias durávies
```

## 4. Persistência

### Tabelas principais (PostgreSQL)

```sql
-- Conversas (uma por canal+usuário)
conversations(id, channel, channel_user_id, started_at, last_active)

-- Mensagens (todas, pra histórico)
messages(id, conversation_id, role, content, tool_calls, ts)

-- Memórias duráveis (curadas)
memories(id, text, tags, embedding vector(384), created_at, score)

-- Skills criadas
skills(id, name, content, created_at, used_count, last_used)

-- Jobs do cron
jobs(id, name, cron_expr, prompt, target_channel, enabled, last_run, next_run)

-- Traces (observabilidade)
traces(id, conversation_id, event_type, data jsonb, ts)
```

## 5. Configuração

### `config/config.yaml`
```yaml
agent:
  name: "Eve"
  default_model: "claude-haiku-4-5"
  max_iterations: 15
  reflection_every: 3
  context_compression_threshold: 0.5

providers:
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
    models:
      planner: "claude-haiku-4-5"
      reflector: "claude-sonnet-4-6"
  ollama:
    host: "http://ollama:11434"
    models:
      memory: "qwen2.5:7b-instruct"

memory:
  postgres_url: ${POSTGRES_URL}
  embedding_model: "paraphrase-multilingual-MiniLM-L12-v2"

channels:
  telegram:
    enabled: true
    token: ${TELEGRAM_BOT_TOKEN}
  discord:
    enabled: false

sandbox:
  default: "docker"
  docker:
    image: "agent-sandbox:latest"
    timeout: 30

fallback_chain:
  - anthropic
  - openrouter
  - ollama
```

## 6. Segurança

- Tools com `requires_confirmation=True` exigem aprovação no canal
- Sandbox Docker por default pra execução de código
- Secrets só em env vars, nunca em config commitado
- Approvals registrados em `traces` pra auditoria
- Rate limiting por canal/usuário no gateway

## 7. Observabilidade

- Logs estruturados (JSON) → stdout → docker logs
- Traces de cada run em `traces` table
- Métricas (Prometheus format) em `/metrics`
- Mission Control UI (fase futura) consome traces pra dashboards
