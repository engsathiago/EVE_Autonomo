# Arquitetura da EVE

Documento de arquitetura completo do agente autônomo EVE.

---

## Princípios

1. **Funcional em todas as fases.** Cada fase entrega um agente que já roda.
2. **Separação clara Python/Node.** Python pensa, Node fala com o mundo.
3. **Plugável.** Tools, transports, canais, skills e sandboxes são carregados dinamicamente.
4. **Observável.** Cada decisão do agente vira um trace estruturado.
5. **Configurável sem código.** SOUL.md, AGENTS.md, TOOLS.md controlam comportamento.

---

## Visão Geral

```
┌────────────────────────────────────────────────────────────┐
│                        Usuário                              │
│   (Telegram / Discord / Slack / Email / Web / CLI)          │
└─────────┬────────────────────────────┬─────────────────────┘
          │                            │
          ▼                            ▼
┌─────────────────────┐   ┌───────────────────────┐
│   Gateway (Node)    │   │   Web Dashboard       │
│   Fastify + Telegraf│   │   HTML + JS + WS      │
│   Port 3000         │   │   Port 8000           │
└────────┬────────────┘   └───────────┬───────────┘
         │ Redis pub/sub              │ HTTP/WS direto
         ▼                            ▼
┌────────────────────────────────────────────────────────────┐
│                    Core Python (FastAPI)                     │
│                         Port 8000                           │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    AIAgent (core.py)                  │   │
│  │          Loop ReAct: Plan → Act → Observe → Reflect  │   │
│  └──────┬─────────────────────────────────────┬─────────┘   │
│         │                                     │             │
│  ┌──────▼──────┐  ┌─────────────┐  ┌─────────▼─────────┐   │
│  │   Tools     │  │   Skills    │  │   Transports      │   │
│  │  Registry   │  │   Manager   │  │  (Anthropic,      │   │
│  │  (builtin   │  │  (loader,   │  │   OpenAI,         │   │
│  │   + custom) │  │   runner,   │  │   Ollama,         │   │
│  └─────────────┘  │   creator)  │  │   OpenRouter)     │   │
│                   └─────────────┘  └───────────────────┘   │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │  Memory     │  │  Scheduler  │  │   Subagents       │   │
│  │  (pgvector  │  │ (APScheduler│  │   (Pool +         │   │
│  │   + FTS +   │  │  + NL parse)│  │    Orchestrator)  │   │
│  │   Curator)  │  └─────────────┘  └───────────────────┘   │
│  └─────────────┘                                           │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │  Missions   │  │   Critic    │  │   Sandbox         │   │
│  │  (Planner + │  │ (3 personas │  │  (subprocess +    │   │
│  │   Reflector)│  │  parallel)  │  │    Docker)        │   │
│  └─────────────┘  └─────────────┘  └───────────────────┘   │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │  Approvals  │  │  Channels   │  │   Fine-tune       │   │
│  │  (Manager + │  │  (Discord,  │  │  (LoRA + bench    │   │
│  │   Scheduler)│  │   Slack,    │  │   + gate)         │   │
│  └─────────────┘  │   Email)    │  └───────────────────┘   │
│                   └─────────────┘                           │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐    ┌────────────────┐
              │  PostgreSQL 16  │    │    Redis 7     │
              │  + pgvector     │    │  (pub/sub +    │
              │  (persistência) │    │    queue)      │
              └─────────────────┘    └────────────────┘
```

---

## Componentes

### AIAgent (core.py)

O coração do sistema. Implementa um loop ReAct com reflexão:

1. **Plan:** recebe um goal e planeja os próximos passos
2. **Act:** executa tool calls via ToolRegistry
3. **Observe:** analisa o resultado
4. **Reflect:** a cada N iterações, reflete sobre o progresso (usa modelo mais potente)
5. **Repeat ou Done:** decide se continua ou entrega o resultado

Configurações:
- `max_iterations`: 15 (default)
- `reflection_every`: 3 iterações
- `context_compression_threshold`: 50% do limite da janela

### Transports

Abstração sobre providers de LLM. Interface única:

```python
async def chat(system, messages, tools) -> {"text", "tool_calls", "raw"}
```

Implementações: `AnthropicTransport`, `OpenAITransport`, `OpenRouterTransport`, `OllamaTransport`.

O `ModelRouter` resolve strings `provider:model_id` e gerencia fallback chain.

### Memory

- **MemoryStore (`store.py`):** PostgreSQL com pgvector para busca semântica (embeddings 384-dim) + FTS multilingual via tsvector.
- **Curator (`curator.py`):** após cada conversa, decide o que persistir como memória durável. Usa Haiku para eficiência.
- **ContextCompressor (`compressor.py`):** quando o contexto ultrapassa 50% do limite, comprime mensagens antigas em sumário.
- **Embeddings (`embeddings.py`):** `paraphrase-multilingual-MiniLM-L12-v2` para suporte PT+EN.

### Skills

Skill = arquivo markdown com frontmatter + instruções. Carregamento e match são dinâmicos.

Componentes:
- **SkillLoader:** varre diretórios e carrega skills
- **SkillManager:** match semântico entre query e skills disponíveis
- **SkillRunner:** executa skill com Jinja2 + tool calls
- **SkillCreator:** observa sessões com 5+ tool calls e propõe novas skills
- **SkillRegistry (F9):** promoção estilo Voyager (draft → active → promoted)
- **SkillValidator:** valida sintaxe e dependências
- **SkillDecayManager:** degrada skills pouco usadas

### Tools

Cada tool: classe Python com `name`, `description`, `input_schema`, `async execute()`.

Tools builtin:
- `read_file` — ler arquivo do workspace
- `write_file` — escrever arquivo (requer confirmação)
- `list_dir` — listar diretório
- `shell` — executar comando (requer confirmação)
- `web_search` — pesquisa web via Tavily/Brave
- `salvar_memoria` — persistir memória semântica
- `ler_memoria` — buscar memórias
- `delegate` — delegar para subagente

### Sandbox

Execução de código isolada:
- **SubprocessBackend:** execução local rápida (dev)
- **DockerBackend:** container efêmero com timeout (produção)
- **Policies:** `POLICY_READONLY`, `POLICY_STANDARD`, `POLICY_NETWORK`, `POLICY_FINETUNE`

### Scheduler

APScheduler com SQLAlchemyJobStore (persistido em Postgres). O parser converte linguagem natural em cron expressions via LLM + validação dupla com croniter.

### Subagentes

- **SubagentPool:** spawn, spawn_parallel, timeout hard, semáforo global
- **SubAgentContext:** isolamento por construção (memory_store=None, skill_manager=None, conversation_id fresh)
- **Orchestrator:** classifica complexidade em tiers (INSTANT/FAST/STRATEGIC/EPIC) e decide quantos subagentes usar
- **Aggregator:** combina resultados parciais de subagentes

### Missões

Planejamento de longo prazo:
- **MissionStore:** PostgreSQL, state machine (active → paused/completed/abandoned)
- **MissionPlanner:** LLM gera steps, suporta `[PARALELO N]` para paralelização
- **MissionReflector:** após cada step, reflete e armazena insights na memória reflexiva

### Critic

3 personas executadas em paralelo via `asyncio.gather`:
1. **Técnico:** avalia viabilidade e riscos técnicos
2. **Advogado do diabo:** desafia premissas e busca falhas
3. **Sintetizador:** recebe os dois pareceres e produz decisão final

Cache de 60s para evitar avaliações duplicadas. Resultados persistidos em `critic_evaluations`.

### Channels (Canais)

#### Via Gateway Node (Telegram)
- Telegraf com long-polling
- OutboundWorker com Bottleneck rate limiter
- Allowlist de chat_ids
- Formatação de mensagens (Markdown, teclados inline)

#### Via Core Python (Discord, Slack, Email)
- Adaptadores com interface `BaseChannelAdapter`
- Cada canal tem seu próprio allowlist obrigatório
- Comandos inline (`/approve`, `/deny`, `/status`)
- Redação de segredos em logs

### Approvals

- **ApprovalManager:** cria e gerencia aprovações pendentes
- **ApprovalScheduler:** expira aprovações após timeout (30min default)
- Integrado com skills que marcam `requires_confirmation = true`

### Fine-tuning

Pipeline completo de fine-tuning LoRA:
1. **TraceCollector:** coleta traces de missões (F7) e skills (F9)
2. **DatasetBuilder:** filtra PII, deduplica, particiona 90/10
3. **LoRATrainer:** Unsloth + fallback para transformers+peft
4. **BenchmarkRunner:** 62 tasks em 6 eixos, juiz Claude
5. **CheckpointGate:** 3 gates (safety, per-axis, overall)
6. **CheckpointRegistry:** ativação atômica, rollback

### Web UI

Dashboard com 8 painéis:
- **Chat:** conversa em tempo real com o agente
- **Missões:** visualização e controle de missões
- **Skills:** listagem e gerenciamento de skills
- **Memória:** busca semântica na memória do agente
- **Traces:** log de execução detalhado
- **Crítico:** fila e histórico de avaliações
- **Subagentes:** status de subagentes em execução
- **Aprovações:** aprovar/negar operações pendentes

WebSocket multiplexado para atualizações em tempo real. Auth via token.

---

## Comunicação Python ↔ Node

```
┌─────────────┐                    ┌─────────────┐
│   Gateway    │  ──── Redis ────> │    Core      │
│   (Node)     │  agent:in         │   (Python)   │
│              │                   │              │
│              │  <── Redis ────   │              │
│              │  agent:out:{ch}   │              │
│              │  agent:stream:{r} │              │
└─────────────┘                    └─────────────┘
```

- **`agent:in`:** Gateway publica mensagens recebidas dos canais
- **`agent:out:{channel_id}`:** Core publica respostas
- **`agent:stream:{request_id}`:** Core publica chunks de streaming
- **HTTP REST:** comunicação síncrona para comandos específicos

---

## Banco de Dados

PostgreSQL 16 com pgvector. Schema distribuído em 12 migrações:

### Tabelas principais

| Tabela | Propósito |
|--------|-----------|
| `conversations` | Sessões de conversa |
| `messages` | Mensagens por conversa |
| `memories` | Memória semântica durável (com embedding vector) |
| `skill_invocations` | Log de execuções de skills |
| `model_invocations` | Log de chamadas LLM (custo, latência, tokens) |
| `pending_approvals` | Aprovações pendentes |
| `cron_jobs` | Jobs agendados (persistência do APScheduler) |
| `tasks` | Tasks de execução |
| `subagent_runs` | Execuções de subagentes |
| `missions` | Missões de longo prazo |
| `mission_steps` | Steps de cada missão |
| `critic_evaluations` | Avaliações do crítico |
| `reflexive_memory` | Insights reflexivos (com embedding vector) |
| `sandbox_executions` | Log de execuções em sandbox |
| `skill_registry` | Registry de skills (F9, Voyager) |
| `channel_messages` | Mensagens de canais extras |
| `finetune_runs` | Runs de fine-tuning |
| `benchmark_results` | Resultados de benchmark |

---

## Segurança

- **Allowlists obrigatórias** em todos os canais (sem allowlist = adapter não sobe)
- **Aprovações** para operações destrutivas (shell, write, delete)
- **Blacklist de comandos** shell (rm -rf /, mkfs, dd, etc.)
- **Workspace paths** limitam acesso do agente ao filesystem
- **Rate limiting** por usuário e por canal
- **Redação de segredos** em logs
- **CSP headers** no web dashboard
- **Auth token** no WebSocket

---

## Observabilidade

- **Logging estruturado** via structlog (JSON em produção)
- **Traces** completos de cada execução (tools, decisões, reflexões)
- **Métricas Prometheus** (12 métricas: tokens, custo, latência, etc.)
- **Event system** (`AgentEvent`) para propagação de eventos
- **model_invocations** para tracking de custo por chamada LLM
