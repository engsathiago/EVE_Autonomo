<p align="center">
  <strong>🤖 EVE — Agente Autônomo</strong>
</p>

<p align="center">
  <a href="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml">
    <img src="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
</p>

<h1 align="center">EVE_Autonomo</h1>

<p align="center">
  Agente de IA autônomo, multi-modelo e multi-canal com memória persistente, skills auto-geradas, missões de longo prazo e fine-tuning local.
</p>

<p align="center">
  <a href="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml"><img src="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/node-20%2B-green.svg" alt="Node 20+" />
  <img src="https://img.shields.io/badge/postgres-16-blue.svg" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/status-em%20desenvolvimento-yellow.svg" alt="Status: Em Desenvolvimento" />
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://github.com/engsathiago/EVE_Autonomo/issues"><img src="https://img.shields.io/github/issues/engsathiago/EVE_Autonomo.svg" alt="Issues" /></a>
</p>

> **Status honesto:** este projeto está em desenvolvimento ativo. Algumas fases têm
> **execução real validada** em runtime (F0, F1, F4 — core, loop, multi-model);
> outras são **parciais** (F2, F3); e a maioria está **implementada mas teórica**
> — o código existe e os testes unitários passam, mas nunca foram exercitadas em
> produção real (F5–F13). A melhoria D.1 (tool routing por step) foi validada com
> replay real. Veja [`docs/audit/PHASE_STATUS.md`](docs/audit/PHASE_STATUS.md) para
> a verdade detalhada e [`docs/known-issues.md`](docs/known-issues.md) para bugs
> conhecidos não corrigidos.

<p align="center">
  <a href="#quickstart">Quickstart</a> •
  <a href="#arquitetura">Arquitetura</a> •
  <a href="#funcionalidades">Funcionalidades</a> •
  <a href="#cli">CLI</a> •
  <a href="#api">API</a> •
  <a href="#configuração">Configuração</a> •
  <a href="#contribuindo">Contribuindo</a>
</p>

---

## O que é a EVE?

EVE é um agente de IA autônomo construído em Python e TypeScript, inspirado no
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) e no
[OpenClaw](https://github.com/steipete/agent) (Peter Steinberger). Ela combina:

- **Do Hermes:** loop autônomo ReAct, memória curada, skills auto-criadas, cron, subagentes, multi-provider, compressão de contexto.
- **Do OpenClaw:** gateway central, configuração via `SOUL.md`, multi-canal, plugins drop-in, sistema de aprovações.

O resultado é uma agente que **pensa, age, aprende e se adapta** — com controle total do operador em cada etapa.

## Funcionalidades

| Módulo | Descrição |
|--------|-----------|
| **Loop ReAct** | Planejamento + execução + reflexão em até 15 iterações por goal |
| **Memória Persistente** | PostgreSQL + pgvector para busca semântica, FTS multilingual, curadoria automática via Haiku |
| **Skills** | Carregamento dinâmico, match semântico, criação automática a partir de sessões, promoção estilo Voyager |
| **Multi-Modelo** | Anthropic, OpenAI, OpenRouter e Ollama com fallback chain configurável |
| **Multi-Canal** | Telegram (Gateway Node), Discord, Slack, E-mail (Core Python) |
| **Aprovações** | Operações sensíveis requerem confirmação humana com timeout configurável |
| **Cron** | Agendamento com linguagem natural → cron expression, persistido em Postgres |
| **Subagentes** | Pool com isolamento, timeout hard, semáforo global e orquestrador com tiers |
| **Missões** | Planejamento multi-step com replanejamento automático e reflexão |
| **Crítico Autônomo** | 3 personas (técnico, advogado do diabo, sintetizador) avaliando ações em paralelo |
| **Sandboxes** | Execução de código em subprocess ou Docker com políticas de segurança |
| **Fine-tuning Local** | LoRA periódico sobre Qwen 2.5 / Llama com benchmark gates automáticos |
| **Web Dashboard** | 8 painéis (chat, missões, skills, memória, traces, crítico, subagentes, aprovações) via WebSocket |
| **CLI Completa** | 11 subcomandos para operar o agente sem abrir um browser |

## Stack Tecnológica

| Camada | Tecnologia |
|--------|------------|
| **Core (cérebro)** | Python 3.11+, FastAPI, asyncio, asyncpg |
| **Gateway (canais)** | Node 20+, TypeScript, Fastify, Telegraf |
| **Banco de Dados** | PostgreSQL 16 + pgvector |
| **Fila/Pubsub** | Redis 7 |
| **Web UI** | HTML + vanilla JS (sem build, sem framework) |
| **Deploy** | Docker Compose → VPS (DigitalOcean / Hetzner) |

## Quickstart

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/install/)
- Uma chave de API da [Anthropic](https://console.anthropic.com/) (ou outro provider LLM)

### Subindo o projeto (forma rápida — estilo OpenClaw)

```bash
# 1. Clone o repositório
git clone https://github.com/engsathiago/EVE_Autonomo.git
cd EVE_Autonomo

# 2. Wizard interativo (escolhe provider, modelo, gera .env)
agent init

# 3. Suba todos os serviços
docker compose up --build -d

# 4. Valide a instalação
agent doctor

# 5. Dashboard de status
agent status

# 6. Converse com a EVE (TUI estilo OpenClaw)
eve                          # ou: agent chat
```

> 💬 **`eve` abre o TUI interativo** com auto-complete, slash commands (`/model`, `/cost`, `/skills`, `/missions`...), troca de modelo ao vivo e renderização Markdown — exatamente como o OpenClaw faz.

### Subindo manualmente (forma tradicional)

```bash
cp .env.example .env       # Edite .env manualmente
docker compose up --build -d
curl http://localhost:8000/health
```

### Com Ollama (modelos locais)

```bash
docker compose --profile local-llm up --build -d
```

### Sem Docker (desenvolvimento local)

```bash
# Core Python
cd core
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn agent.server:app --reload --port 8000

# Gateway Node (outro terminal)
cd gateway
npm install
npm run dev
```

Veja [docs/INSTALACAO.md](docs/INSTALACAO.md) para o guia completo de instalação.

### Primeiros Passos

Após subir o projeto, explore os exemplos práticos:

- 🟢 [Primeira conversa](examples/01_primeira_conversa/) — Hello world via CLI/API/Web
- 🟢 [Criando uma skill custom](examples/02_criando_skill_custom/) — Skills personalizadas em Markdown
- 🟡 [Configurando Telegram](examples/03_configurando_telegram/) — Bot em 5 minutos
- 🟡 [Missão multi-step](examples/04_missao_complexa/) — Tarefas autônomas longas
- 🔴 [Plugin custom tool](examples/05_plugin_custom_tool/) — Estendendo a EVE
- 🔴 [Fine-tuning workflow](examples/06_finetuning_workflow/) — LoRA local

Veja também [docs/PLUGINS.md](docs/PLUGINS.md) para desenvolver extensões.

## Arquitetura

```
                    ┌─────────────────────────────────┐
                    │          Web Dashboard           │
                    │    (HTML + JS + WebSocket)       │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
                    │        Core Python (FastAPI)      │
                    │                                   │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │ AIAgent │  │   Memória     │   │
                    │  │  ReAct  │  │  (pgvector)   │   │
                    │  └────┬────┘  └──────────────┘   │
                    │       │                           │
                    │  ┌────▼────┐  ┌──────────────┐   │
                    │  │  Tools  │  │   Skills      │   │
                    │  │Registry │  │  (auto-gen)   │   │
                    │  └─────────┘  └──────────────┘   │
                    │                                   │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │  Cron   │  │  Subagentes   │   │
                    │  │Scheduler│  │    + Pool     │   │
                    │  └─────────┘  └──────────────┘   │
                    │                                   │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │Missões  │  │   Crítico     │   │
                    │  │+Planner │  │  (3 personas) │   │
                    │  └─────────┘  └──────────────┘   │
                    │                                   │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │Sandbox  │  │  Fine-tune    │   │
                    │  │(Docker) │  │  (LoRA)       │   │
                    │  └─────────┘  └──────────────┘   │
                    └──────────┬──────────────────────┘
                               │ Redis pub/sub
                    ┌──────────▼──────────────────────┐
                    │      Gateway Node (Fastify)      │
                    │                                   │
                    │  ┌─────────┐  ┌──────────────┐   │
                    │  │Telegram │  │  Outbound     │   │
                    │  │  Bot    │  │  Dispatcher   │   │
                    │  └─────────┘  └──────────────┘   │
                    └──────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
         Telegram          Discord           Slack
```

Veja [docs/ARQUITETURA.md](docs/ARQUITETURA.md) para detalhes completos.

## Estrutura do Projeto

```
EVE_Autonomo/
├── core/                    # Cérebro do agente (Python)
│   ├── src/agent/
│   │   ├── core.py          # Loop ReAct principal
│   │   ├── server.py        # Servidor FastAPI
│   │   ├── config.py        # Configuração centralizada
│   │   ├── api/             # Rotas REST (mensagens, cron, missões, etc.)
│   │   ├── approvals/       # Sistema de aprovações humanas
│   │   ├── autonomous/      # Loop autônomo (tick periódico)
│   │   ├── channels/        # Adaptadores multi-canal (Discord, Slack, Email)
│   │   ├── critic/          # Crítico autônomo (3 personas)
│   │   ├── finetune/        # Fine-tuning LoRA local
│   │   ├── memory/          # Memória persistente (pgvector + FTS)
│   │   ├── metrics/         # Métricas Prometheus
│   │   ├── missions/        # Missões de longo prazo
│   │   ├── models/          # Multi-modelo (Anthropic, OpenAI, Ollama, etc.)
│   │   ├── observability/   # Logging estruturado
│   │   ├── orchestrator/    # Orquestrador de tiers
│   │   ├── prompts/         # System prompts
│   │   ├── sandbox/         # Sandboxes de execução
│   │   ├── scheduler/       # APScheduler + parser de linguagem natural
│   │   ├── skills/          # Skills dinâmicas
│   │   ├── subagents/       # Pool de subagentes
│   │   ├── tasks/           # Store de tasks
│   │   ├── tools/           # Tools builtin
│   │   ├── transports/      # Abstração de transporte LLM
│   │   └── web/             # Servidor web UI
│   ├── migrations/          # Migrações SQL (002 a 014)
│   └── tests/               # ~130 arquivos de teste
├── gateway/                 # Gateway de canais (TypeScript)
│   ├── src/
│   │   ├── index.ts         # Servidor Fastify
│   │   ├── channels/        # Telegram bot (Telegraf)
│   │   ├── outbound/        # Dispatcher + Worker com rate limiting
│   │   └── auth/            # Allowlist de chat_ids
│   └── tests/
├── cli/                     # CLI do agente (Typer + Rich)
│   └── src/cli/             # 11 subcomandos
├── webui/                   # Dashboard web (HTML + vanilla JS)
│   └── public/              # 8 painéis interativos
├── config/                  # Configuração editável sem redeployar
│   ├── SOUL.md              # Personalidade e limites éticos
│   ├── AGENTS.md            # Regras operacionais
│   ├── TOOLS.md             # Documentação das tools
│   └── config.yaml          # Modelos, providers, limites
├── skills/                  # Skills ativas e drafts
├── benchmarks/              # Tasks de benchmark para fine-tuning
├── deploy/                  # Scripts de deploy
├── docs/                    # Documentação completa
├── docker-compose.yml       # Orquestração dos serviços
├── Dockerfile.python        # Multi-stage build do core
├── Dockerfile.node          # Multi-stage build do gateway
└── .env.example             # Template de variáveis de ambiente
```

## CLI

A EVE inclui uma CLI completa construída com [Typer](https://typer.tiangolo.com/) e [Rich](https://rich.readthedocs.io/):

```bash
# Conversar com o agente
agent run "Resuma os logs de hoje"
agent run --model ollama:qwen2.5:7b "O que é Docker?"

# Gerenciar skills
agent skill list
agent skill show backup-postgres
agent skill run backup-postgres
agent skill create-from-session <session_id>

# Agendar tarefas
agent cron add "toda terça às 9h" "Checar se há PRs abertos"
agent cron list
agent cron run-now <job_id>

# Gerenciar missões
agent mission create "Migrar banco para schema v2"
agent mission list
agent mission show <mission_id>

# Modelos
agent model list
agent model health
agent model test anthropic:claude-haiku-4-5 "Oi, tudo bem?"
agent model costs --since today

# Crítico autônomo
agent critic history
agent critic stats

# Fine-tuning local
agent finetune run
agent finetune list
agent finetune activate <checkpoint_id>
agent finetune rollback

# Loop autônomo
agent loop status
agent loop pause / agent loop resume

# Web dashboard
agent web start
```

Veja [docs/CLI.md](docs/CLI.md) para a referência completa.

## API

O Core expõe uma API REST via FastAPI (porta 8000 por padrão).

### Endpoints principais

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/v1/messages` | Enviar mensagem para o agente |
| `GET` | `/v1/approvals` | Listar aprovações pendentes |
| `POST` | `/v1/approvals/{id}` | Aprovar/negar operação |
| `POST` | `/v1/cron/jobs` | Criar job agendado |
| `GET` | `/v1/cron/jobs` | Listar jobs |
| `POST` | `/v1/missions` | Criar missão |
| `GET` | `/v1/missions` | Listar missões |
| `POST` | `/v1/missions/{id}/replan` | Replanejar missão |
| `GET` | `/v1/tasks` | Listar tasks |
| `GET` | `/v1/loop/status` | Status do loop autônomo |
| `GET` | `/v1/critic/evaluations` | Avaliações do crítico |
| `GET` | `/v1/memory/reflexive` | Memória reflexiva |
| `GET` | `/health` | Health check |

### Web Dashboard API

| Método | Rota | Descrição |
|--------|------|-----------|
| `WS` | `/api/v1/stream` | WebSocket multiplexado (tempo real) |
| `GET` | `/web/api/missions` | Missões |
| `GET` | `/web/api/skills` | Skills |
| `POST` | `/web/api/memory/search` | Busca semântica |
| `GET` | `/web/api/traces` | Traces de execução |
| `GET` | `/web/api/critic/history` | Histórico do crítico |
| `GET` | `/web/api/metrics/summary` | Métricas consolidadas |
| `GET` | `/web/api/system/info` | Informações do sistema |

Veja [docs/API.md](docs/API.md) para a referência completa com exemplos.

## Configuração

### Variáveis de Ambiente

O arquivo `.env.example` documenta todas as variáveis. As mais importantes:

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `ANTHROPIC_API_KEY` | Sim* | Chave da API Anthropic |
| `POSTGRES_URL` | Sim | URL de conexão do PostgreSQL |
| `REDIS_URL` | Sim | URL de conexão do Redis |
| `TELEGRAM_BOT_TOKEN` | Não | Token do bot Telegram |
| `DEFAULT_MODEL` | Não | Modelo padrão (ex: `anthropic:claude-haiku-4-5`) |
| `MODEL_FALLBACK_CHAIN` | Não | Chain de fallback (CSV) |
| `OLLAMA_BASE_URL` | Não | URL do Ollama para modelos locais |

*\* Ao menos um provider LLM é necessário.*

### Arquivos de Configuração

| Arquivo | Propósito |
|---------|-----------|
| `config/SOUL.md` | Personalidade, tom de voz e limites éticos |
| `config/AGENTS.md` | Regras operacionais (confirmações, erros, iterações) |
| `config/TOOLS.md` | Documentação das tools disponíveis |
| `config/config.yaml` | Modelos, providers, limites, sandbox, critic |

### Multi-Modelo

A EVE suporta múltiplos providers de LLM com a sintaxe `provider:model_id`:

```
anthropic:claude-sonnet-4-6        # Claude (padrão)
openai:gpt-4o-mini                  # OpenAI
openrouter:deepseek/deepseek-chat   # OpenRouter
ollama:qwen2.5:7b                   # Ollama (local, gratuito)
ollama:gpt-oss:120b                 # Ollama Cloud (com OLLAMA_API_KEY)
```

O mesmo `OllamaTransport` suporta **local** (`OLLAMA_BASE_URL=http://localhost:11434`) ou **cloud** (`OLLAMA_BASE_URL=https://ollama.com` + `OLLAMA_API_KEY=...`). Veja [docs/OLLAMA_CLOUD.md](docs/OLLAMA_CLOUD.md).

Fallback chain: se o provider principal falhar (timeout, 5xx), a EVE tenta automaticamente o próximo da chain.

## Fine-tuning Local

A EVE pode ser periodicamente ajustada (LoRA) sobre modelos locais usando traces reais.

**Regra: sem benchmark aprovado, nenhum checkpoint é ativado.**

```bash
agent finetune bench --model base    # Estabelecer baseline
agent finetune run                   # Executar ciclo completo
agent finetune activate <id>         # Ativar checkpoint aprovado
agent finetune rollback              # Reverter se necessário
```

Cada ciclo: coleta traces → filtra PII → treina QLoRA 4-bit → avalia com 62 tasks em 6 eixos → rejeita se inferior ao baseline.

Veja [docs/finetune.md](docs/finetune.md) para o runbook completo.

## Migrações de Banco

As migrações SQL ficam em `core/migrations/` e são aplicadas na inicialização:

| Migração | Conteúdo |
|----------|----------|
| `002` | Memória (conversations, messages, memories + pgvector) |
| `003` | Skills (skill_invocations) |
| `004` | Multi-modelo (model_invocations) |
| `005` | Aprovações (pending_approvals) |
| `006` | Sessões (conversation_session_id) |
| `007` | Cron + Tasks (cron_jobs, tasks, subagent_runs) |
| `008` | Missões + Crítico (missions, steps, critic_evaluations, reflexive_memory) |
| `009` | Sandboxes (sandbox_executions) |
| `010` | Skills v2 (skill_registry, skill_executions) |
| `012` | Web UI (web_sessions, traces) |
| `013` | Canais extras (channel_messages) |
| `014` | Fine-tuning (finetune_runs, checkpoints, benchmark_results) |

## Testes

```bash
# Testes Python (core) — ~130 arquivos
cd core
pytest                          # Todos os testes
pytest -m "not integration"     # Sem testes de integração
pytest -m "not docker"          # Sem testes que requerem Docker
pytest -m "not slow"            # Sem testes lentos (GPU)

# Testes Node (gateway)
cd gateway
npm test
```

## Roadmap

> Legenda: ✅ validada em runtime — ⚠️ parcial — 🔬 teórica (código + testes, sem runtime real) — 🚧 em andamento — ⏳ não iniciada
>
> Detalhes e evidências: [`docs/audit/PHASE_STATUS.md`](docs/audit/PHASE_STATUS.md)

| # | Fase | Status |
|---|------|--------|
| 0 | Fundação (Docker, Postgres, Redis, projeto base) | ✅ validada |
| 1 | Core mínimo (AIAgent + 4 tools + CLI) | ✅ validada |
| 2 | Memória persistente (pgvector + FTS + Curator + Compressor) | ⚠️ parcial |
| 3 | Skills builtin (loader, runner; criação dinâmica = teórica) | ⚠️ parcial |
| 4 | Multi-modelo (Anthropic, OpenAI, OpenRouter, Ollama) | ✅ validada |
| 5 | Gateway Node + Telegram + Aprovações | 🔬 teórica |
| 6 | Cron + Subagentes + Orquestrador com Tiers | 🔬 teórica |
| 7 | Missões persistentes + Crítico autônomo + Loop | 🔬 teórica |
| 8 | Sandboxes de execução (subprocess + Docker) | 🔬 teórica |
| 9 | Skills auto-geradas estilo Voyager | 🔬 teórica |
| 10 | Deploy VPS (supervisor, health, métricas, backup) | 🔬 teórica |
| 11 | Web UI Dashboard (8 painéis, WebSocket, auth) | 🔬 teórica |
| 12 | Canais extras (Discord, Slack, E-mail) | 🔬 teórica |
| 13 | Fine-tuning local periódico (LoRA + benchmark gates) | 🔬 teórica |
| A | Auditoria de execução real (Fase A) | ✅ concluída |
| B | Fix do executor (validação de tool calls) | ✅ concluída |
| D.1 | Tool routing por step | ✅ validada |
| D.5 | Re-validação F5–F13 em runtime real | ⏳ candidato próximo |
| D.6 | Skills permissions + router wired | 🚧 em andamento |
| 14 | RLAIF (Reinforcement Learning from AI Feedback) | ⏳ não iniciada |

## Fine-tuning local

O agente pode ser periodicamente ajustado (LoRA) sobre o modelo local (Qwen 2.5 7B / Llama 3.x)
usando traces reais de missões e skills executadas.

**Regra principal: sem benchmark aprovado, nenhum checkpoint é ativado.**

```bash
# 1. Instalar dependências de fine-tuning (separado da instalação base)
pip install 'agent-core[finetune]'

# 2. Estabelecer baseline do modelo base
agent finetune bench --model base

# 3. Executar um ciclo completo
agent finetune run

# 4. Ver resultado
agent finetune list
agent finetune report <run_id>

# 5. Ativar manualmente (sempre manual nas 5 primeiras rodadas)
agent finetune activate <checkpoint_id>

# 6. Rollback se necessário
agent finetune rollback
```

Cada run:
- Coleta traces da F7 (missões) e F9 (skills) dos últimos 30 dias
- Filtra PII básico (email, CPF, telefone) e deduplica
- Avalia base e candidato com 62 tasks fixas distribuídas em 6 eixos
- Rejeita automaticamente se score < base+3%, qualquer eixo caiu >5%, ou safety regrediu
- Gera relatório markdown em `models/checkpoints/<id>/benchmark_report.md`

Veja `docs/finetune.md` para o runbook completo, troubleshooting de VRAM e custo Claude por run.

## Licença

Este projeto está licenciado sob a [MIT License](LICENSE).

## Contribuindo

Contribuições são bem-vindas! Veja [CONTRIBUTING.md](CONTRIBUTING.md) para o guia completo.

---

<p align="center">
  Feito com dedicação por <strong>Thiago</strong>
</p>
