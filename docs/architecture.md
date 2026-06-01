# EVE_Autonomo — Arquitetura v1.0

## Visão geral

EVE é um agente autônomo multi-modelo, multi-canal com memória persistente, skills auto-geradas e missões de longo prazo. É composto por 4 pacotes principais que se comunicam via Redis pub/sub e HTTP REST.

```
┌─────────────────────────────────────────────────────────┐
│                      EVE_Autonomo                        │
│                                                           │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │   core (Py)  │◄──►│  gateway(TS) │◄──►│  webui(JS) │  │
│  │  FastAPI 8000│    │  Fastify 3000│    │  nginx 8080│  │
│  └──────┬───────┘    └──────┬───────┘    └────────────┘  │
│         │                   │                             │
│  ┌──────▼───────┐    ┌──────▼───────┐                    │
│  │  PostgreSQL  │    │    Redis      │                    │
│  │  + pgvector  │    │  pub/sub +    │                    │
│  │  port 5432   │    │  queue 6379   │                    │
│  └──────────────┘    └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

## Pacote core (Python 3.11+)

O coração do agente. Expõe API FastAPI e contém todos os subsistemas.

```
core/src/agent/
├── server.py          # FastAPI + lifespan (monta todos os subsistemas)
├── core.py            # AIAgent: loop ReAct, tool dispatch, eventos
├── config.py          # Settings (pydantic-settings, config.yaml + env vars)
├── transports/        # Anthropic, OpenAI, OpenRouter, Ollama
├── memory/            # MemoryStore (pgvector), Curator, ContextCompressor
├── skills/            # SkillManager (F3) + SkillSynthesizer (F9)
├── missions/          # MissionStore, MissionPlanner, MissionReflector
├── critic/            # Critic 3 personas + CriticGating
├── autonomous/        # AutonomousLoop (APScheduler)
├── sandbox/           # SubprocessSandbox, DockerSandbox, 5 perfis
├── channels/          # ChannelAdapter ABC, Discord/Slack/Email
├── orchestrator/      # Tiers INSTANT/FAST/STRATEGIC/EPIC, tool routing
├── db/                # apply_migrations, stamp_all
├── deploy/            # Supervisor, health endpoints, backup
├── web/               # FastAPI web module, auth, routes
└── finetune/          # LoRA trainer, benchmark runner, checkpoint gate
```

## Pacote gateway (TypeScript/Node 20+)

Proxy de mensagens entre canais externos e o core Python.

```
gateway/src/
├── server.ts          # Fastify + healthcheck
├── telegram/          # Telegraf long-polling, approval flow
├── approvals/         # ApprovalManager, ApprovalScheduler
├── outbound/          # OutboundDispatcher (Redis) + worker (Bottleneck)
└── redis/             # Redis pub/sub client
```

**Comunicação Redis:**
- `agent:in` — gateway publica mensagens recebidas dos canais
- `agent:out:{channel_id}` — core publica respostas
- `agent:stream:{request_id}` — core publica chunks de streaming
- `outbound:telegram` — core publica mensagens a enviar

## Pacote cli (Python)

CLI de controle do agente. Entry-points: `agent` e `eve` (alias para `agent chat`).

```
cli/src/cli/
├── main.py            # Typer app principal (20+ subcomandos)
├── chat_cmd.py        # TUI interativo com prompt_toolkit
├── db_cmd.py          # agent db migrate [--dry-run] [--stamp]
├── missions.py        # agent mission list/create/pause/resume
├── skills.py          # agent skill list/show/run/validate
├── skills_cmd.py      # agent skills (F9: synthesize, promote, reject)
├── cron.py            # agent cron add/list/enable/disable
├── deploy_cmd.py      # agent deploy install/start/stop/backup
└── web_cmd.py         # agent web start/token-show/open
```

## Pacote webui (HTML/JS vanilla)

Dashboard terminal-style. Sem build step — HTML/JS/CSS direto.

```
webui/public/
├── index.html         # 8 painéis, auth overlay
├── css/term.css       # Tema terminal dark
└── js/
    ├── app.js         # Boot, auth, métricas
    ├── api.js         # fetch wrapper com X-Agent-Token
    ├── ws.js          # WebSocket multiplexado
    └── panels/        # chat, missions, skills, memory, traces,
                       # critic, subagents, approvals
```

**Para desenvolvimento local:**
```bash
PYTHONPATH=core/src core/.venv/bin/python scripts/run_webui.py
# Abre http://localhost:8080/?token=<token>
```

## Fluxo de uma missão

```
Usuário cria missão
       │
       ▼
MissionStore.create()
       │
       ▼
MissionPlanner → LLM → lista de steps (com tools_required)
       │
       ▼
AutonomousLoop.tick() [a cada 5min]
       │
       ├─► get_pending_steps()
       │
       └─► _dispatch_step()
              │
              ├─► needs_critic(decision)?
              │      └─► Critic.evaluate() [3 personas]
              │             ├─► approve → continua
              │             ├─► reject → step=failed
              │             └─► escalate → step=skipped, approval pending
              │
              ├─► Task criada (com tools_required propagados)
              │
              └─► Orchestrator.route(task)
                     │
                     ├─► TierClassifier → INSTANT/FAST/STRATEGIC/EPIC
                     │
                     └─► AIAgent.run(task)
                            │
                            ├─► exec_tool() [via sandbox]
                            │
                            └─► analyze_turn() → EXECUTED / PROSE_ONLY
```

## Pontos de extensão

| Tipo | Interface | Exemplo |
|------|-----------|---------|
| Transport (LLM) | `agent.models.base.BaseTransport` | OllamaTransport, AnthropicTransport |
| Tool | `agent.tools.registry.ToolRegistry` | `register_builtin()` |
| Skill (F3) | YAML manifest + Jinja2 template | `skills/summarize_text/` |
| Skill (F9) | Python script + manifest.yaml | SkillSynthesizer auto-gerado |
| Channel | `agent.channels.base.ChannelAdapter` | DiscordAdapter, SlackAdapter |
| Sandbox | `agent.sandbox.base.BaseSandbox` | SubprocessSandbox, DockerSandbox |

## Banco de dados

16 migrations em `core/migrations/`. Aplicadas automaticamente no boot via `agent.db.migrate`.

Para bootstrapping de DB existente sem tracking: `agent db migrate --stamp`
