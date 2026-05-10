# Agente Autônomo — Instruções Mestre

> Este arquivo é lido automaticamente pelo Claude Code em toda sessão.
> Ele contém o contexto global do projeto. Atualize quando algo mudar.

## Visão geral

Construindo um agente autônomo inspirado em **Hermes Agent** (Nous Research) e
**OpenClaw** (Peter Steinberger). Pega o melhor dos dois:

- **Do Hermes:** loop autônomo, memória curada, skills auto-criadas, cron,
  subagentes, multi-provider, ContextCompressor.
- **Do OpenClaw:** gateway central, config via SOUL.md, multi-canal, plugins
  drop-in, MCP nativo, approvals.

## Stack

- **Core:** Python 3.11+, FastAPI, asyncio, asyncpg, ChromaDB-compatible via pgvector
- **Gateway:** Node 20+, TypeScript, Fastify, telegraf/discord.js/baileys
- **DB:** PostgreSQL 16 (com pgvector)
- **Bus:** Redis 7 (pubsub + queue)
- **Web UI:** HTML + vanilla JS (sem build, sem framework)
- **Deploy:** Docker Compose em VPS (DigitalOcean/Hetzner)

## Convenções

### Python
- async/await em todo IO
- Type hints sempre, validação com pydantic v2
- Imports absolutos (`from agent.tools.registry import ...`)
- Erros encapsulados, nunca `except: pass`
- Logging estruturado via `agent.observability.logger`
- Testes com pytest + pytest-asyncio

### TypeScript
- Strict mode no tsconfig
- ESM (`"type": "module"`)
- Zod pra validação
- Pino pra logs
- Testes com vitest

### Geral
- Commits conventional: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- Cada arquivo novo precisa de teste correspondente
- Nada de comentários óbvios; só explicar o "porquê", não o "o quê"

## Estado atual do projeto

> ATUALIZE ESTA SEÇÃO APÓS CADA FASE

- [x] Fase 0: Fundação
- [x] Fase 1: Core mínimo
- [x] Fase 2: Memória — MemoryStore (pgvector + FTS multilingual, busca híbrida via RRF), Curator (Haiku 4.5) decidindo o que persistir, ContextCompressor para histórico longo, tools `salvar_memoria` e `ler_memoria`, persistência cross-sessão validada (E2E OpenClaw passou)
- [x] Fase 3: Skills — SkillManager (loader + registry + match semântico via embedder da F2), SkillRunner (Jinja2 + tool calls), SkillCreator (extração de sessão → draft), 4 skills builtin, tabela `skill_invocations`, integração no AIAgent (skill__ tools + inject no system prompt), CLI `agent skill list/show/run/validate/review/create-from-session`
- [x] Fase 4: Multi-modelo — Transport Protocol unificado, AnthropicTransport/OpenAITransport/OpenRouterTransport/OllamaTransport, ModelRouter (resolução `provider:model`, fallback chain, capability check), tabela `model_invocations` (custo/latência/tokens por chamada), descoberta de capabilities via `/api/show` + tabela por família, CLI `agent model list/health/show/test/costs`, `agent run --model`, `summarize_text` skill aponta para Ollama
- [x] Fase 5: Gateway Node + Telegram — Gateway TypeScript (Telegraf long-polling), ApprovalManager com tabela `pending_approvals`, ApprovalScheduler (expiração 30min), OutboundDispatcher (Redis `outbound:telegram`), OutboundWorker (BRPOP + Bottleneck rate limiter), `POST /v1/messages` + `POST /v1/approvals/{id}` no core, skill `mock_send_email` como demo de aprovação, allowlist de chat_ids, 15 testes Python + 20 testes TypeScript
- [x] Fase 6: Cron + Subagentes — APScheduler (AsyncIOScheduler + SQLAlchemyJobStore persistido em Postgres, sobrevive a restart), CronWorker (injeção de scheduler para testabilidade), NL→cron via LLM + croniter double-validation, TaskStore (tasks + subagent_runs), SubagentPool (spawn, spawn_parallel, timeout hard, semáforo global), SubAgentContext (isolamento por construção: memory_store=None, skill_manager=None, conversation_id fresh), Orchestrator (TierClassifier com cache TTL 5min via ModelRouter Haiku, tiers INSTANT/FAST/STRATEGIC/EPIC, Aggregator partial=true), tool `delegate` builtin, event_registry no ApprovalManager para propagação async de approvals de subagentes, rotas REST /v1/cron e /v1/tasks, CLI `agent cron add/list/show/enable/disable/remove/run-now` + `agent task list/show/tree/cancel/stats`, migration 007_cron_tasks.sql, server.py migrado para lifespan, 74 novos testes passando
- [x] Fase 7: Missões Persistentes + Crítico Autônomo — MissionStore (PostgreSQL, status machine active→paused/completed/abandoned), MissionPlanner (LLM→steps com prefixo [PARALELO N], replan automático), MissionReflector (parse rígido 4-campos, reflexive_memory.add), Critic (3 personas em asyncio.gather: technical+devils_advocate paralelo → synthesizer recebe ambos; cache 60s, persiste critic_evaluations), ReflexiveMemory (pgvector VECTOR(384), decay via forgotten flag), AutonomousLoop (tick a cada 5min via APScheduler, MAX_STEPS_PER_TICK=3, sem LLM direto), SkillManifest.irreversible, CriticSettings+MissionsSettings em config.yaml, Phase7Metrics (Prometheus), migration 008_missions_critic.sql, rotas REST /v1/missions /v1/critic /v1/memory/reflexive /v1/loop, CLI agent mission/critic/memory/loop, 229 testes passando (27 novos F7)
- [ ] Fase 8: Sandboxes
- [ ] Fase 9: Skills auto-geradas estilo Voyager
- [ ] Fase 10: Deploy VPS
- [ ] Fase 11: Web UI
- [ ] Fase 12+: Canais extras + plugins
- [ ] Fase 13: Fine-tuning local periódico (LoRA)
- [ ] Fase 14+: RLAIF

## Diretrizes para o Claude Code

1. **Sempre planejar antes de codar.** Para qualquer mudança em mais de 2
   arquivos, gere primeiro um plano e espere aprovação.

2. **Use as skills locais.** Sempre que possível, use as skills em
   `.claude/skills/`. Elas têm o padrão correto.

3. **Escopo restrito.** Mexa apenas nos arquivos solicitados. Se precisar
   tocar em outros, pergunte.

4. **Testes não são opcionais.** Todo arquivo novo precisa de teste.

5. **Não invente APIs externas.** Se uma biblioteca tem comportamento
   incerto, busque a documentação real ou pergunte.

6. **Mantenha o agente funcional.** Cada fase deve deixar o sistema rodando.
   Nunca faça commits que quebrem o build.

7. **Atualize CLAUDE.md.** Quando concluir uma fase, marque o checkbox e
   atualize a seção de estado.

## Estrutura do projeto

```
agent/
├── core/          # Python (AIAgent, memória, skills, tools)
├── gateway/       # Node (canais de mensagem)
├── webui/         # HTML/JS estático
├── cli/           # Python CLI
├── config/        # SOUL.md, AGENTS.md, TOOLS.md, config.yaml
├── deploy/        # Scripts e configs de deploy
├── docs/
│   ├── architecture.md
│   ├── phases/    # Specs de cada fase
│   └── decisions/ # ADRs (Architecture Decision Records)
└── .claude/
    ├── skills/    # Padrões reutilizáveis
    └── agents/    # Subagentes especialistas
```

## Comunicação Python ↔ Node

- **Mensagens em tempo real:** Redis pubsub
  - Canal `agent:in` — Node publica mensagens recebidas dos canais
  - Canal `agent:out:{channel_id}` — Python publica respostas
  - Canal `agent:stream:{request_id}` — Python publica chunks de streaming
- **Comandos:** HTTP REST entre os serviços
  - Python expõe `/api/chat`, `/api/jobs`, `/api/skills`
  - Node expõe `/api/send`, `/api/health`
- **Streaming:** Server-Sent Events do Python pro Web UI direto

## Variáveis de ambiente

Veja `.env.example`. Nunca commite `.env` real.

## Modelos recomendados

- **Planner/Reasoner do agente:** `claude-haiku-4-5` (rápido, tool use confiável)
- **Reflector/Critic:** `claude-sonnet-4-6` (raciocínio profundo)
- **Memória/Sumarização:** `qwen2.5:7b-instruct` via Ollama (local, grátis)
- **Embeddings:** `paraphrase-multilingual-MiniLM-L12-v2` (PT+EN)

## Multi-modelo (Fase 4)

Formato de string: `provider:model_id` — ex: `anthropic:claude-haiku-4-5`, `ollama:qwen2.5:7b`

| Provider | Exemplo | Notas |
|---|---|---|
| `anthropic` | `anthropic:claude-sonnet-4-7` | Default. Requer `ANTHROPIC_API_KEY` |
| `openai` | `openai:gpt-4o-mini` | Requer `OPENAI_API_KEY` |
| `openrouter` | `openrouter:deepseek/deepseek-chat` | Requer `OPENROUTER_API_KEY` |
| `ollama` | `ollama:qwen2.5:7b` | Local. Requer Ollama rodando em `OLLAMA_BASE_URL` |

Fallback chain: `MODEL_FALLBACK_CHAIN=ollama:qwen2.5:7b,anthropic:claude-haiku-4-5` (vazio = sem fallback).
Só dispara em erros de infra (timeout, 5xx). Rate limit (429) e auth errors não disparam fallback.

Custo: cada invocação LLM grava em `model_invocations`. Ver gastos: `agent model costs --since today`.

## O que NÃO fazer

- ❌ Não use `print()` — use o logger.
- ❌ Não bloqueie a event loop com chamadas síncronas pesadas.
- ❌ Não escreva em arquivos sem `pathlib`.
- ❌ Não hardcode credenciais; use env vars.
- ❌ Não crie bibliotecas Python sem `pyproject.toml`.
- ❌ Não use `any` em TypeScript sem motivo justificado por comentário.

## Débito técnico — testes Python em Docker (mai/2026)

Estado da suite ao fechar Fase 5:
- 142 testes passing
- 46 failing (pre-existentes, expostos pela primeira vez ao rodar em Docker)
- 3 skipped
- Testes da Fase 5 (15 em tests/api/ e tests/approvals/): 100% passing.

Arquivos com testes quebrados:
- tests/skills/test_runner.py (TestManagerRun, TestSkillRunnerExecute)
- tests/skills/test_manager.py (TestManagerMatch)
- tests/skills/test_creator.py — 7 testes async sem plugin asyncio, pré-F4 (commit 9dbc33a52)
- tests/agent/memory/test_compressor.py
- tests/agent/memory/test_curator.py
- tests/agent/memory/test_memory_tools.py
- tests/agent/memory/test_store.py
- tests/integration/test_memory_persistence.py
- tests/test_config.py

Causa: testes foram escritos pra rodar em .venv local com pytest-asyncio mode antigo;
ao migrar pra Docker (Dockerfile.python target=dev) versões mais novas das libs
exibem incompatibilidades que sempre estiveram presentes.

A resolver em fase de manutenção dedicada — não bloqueia Fase 5.
