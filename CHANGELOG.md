# Changelog

Todas as mudanças notáveis neste projeto serão documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [Unreleased]

### Adicionado
- **`agent chat` (alias: `eve`) — TUI interativo estilo OpenClaw:** Chat dedicado com banner permanente (modelo, tokens, custo, tempo), auto-complete de comandos via prompt_toolkit, histórico persistente, renderização Markdown nas respostas, e 12 slash commands:
  - `/model [novo]` — troca modelo **ao vivo** sem sair
  - `/clear`, `/cost`, `/reset`
  - `/tools`, `/skills`, `/missions`, `/approvals` — inspeção rápida
  - `/save [arquivo.md]` — exporta conversa
  - `/help`, `/exit`
- **Entry-point `eve`** instalável via `pip install -e cli` para invocar diretamente sem `agent chat`.
- **CLI estilo OpenClaw/Hermes:** 4 novos comandos para setup e operação fluida:
  - `agent init` — wizard interativo (escolhe provider, modelo, testa conexão, grava .env)
  - `agent config show/use/set/get/models/providers` — gerenciamento estilo `gcloud config`
  - `agent status [--detailed]` — dashboard com provider, infra, métricas 24h
  - `agent doctor` — 11 checks de validação (Python, .env, config, providers, DB, Redis, migrações)
- **Ollama Cloud:** suporte a `OLLAMA_API_KEY` no `OllamaTransport`. Mesmo transport funciona local (`http://localhost:11434`) ou cloud (`https://ollama.com`). Inclui detecção de erros 401/403 com mensagem clara, propriedade `is_cloud`, documentação em `docs/OLLAMA_CLOUD.md`.
- **Infraestrutura open-source:** CI GitHub Actions (pytest + ruff + npm test + gitleaks), pre-commit hooks, `SECURITY.md` com threat model, `CHANGELOG.md`, issue/PR templates, `CODEOWNERS`, badges no README.
- **Exemplos práticos:** 6 tutoriais do iniciante ao avançado em `examples/`.
- **Plugin development guide:** `docs/PLUGINS.md` documentando Tools, Skills, Transports, Channels, Sandboxes.

### Planejado
- Fase 14: RLAIF (Reinforcement Learning from AI Feedback)
- Plugin marketplace
- Web dashboard mobile-friendly
- Integração com WhatsApp via WhatsApp Business API

---

## [0.13.0] — 2026-05-15 — Fine-tuning Local

### Adicionado
- **Fase 13:** Fine-tuning LoRA local sobre modelos Qwen 2.5 / Llama
- 9 módulos de fine-tuning: `trace_collector`, `dataset_builder`, `lora_trainer`, `benchmark_runner`, `checkpoint_gate`, `checkpoint_registry`, `reports`, `safety_check`, `rubric`
- 62 tasks de benchmark em 6 eixos de qualidade
- POLICY_FINETUNE com allowlist HuggingFace para download seguro
- Migration `014_finetune.sql`
- CLI `agent finetune run/list/activate/rollback/bench`
- 70 testes (C1–C14 cobertos)
- 7 eventos `finetune.*` no event_registry

### Segurança
- Safety check com prompts adversariais
- Per-axis gate (nenhum eixo pode regredir > 5%)
- Filtro PII (email, CPF, telefone) em datasets

---

## [0.12.0] — 2026-05-10 — Canais Extras

### Adicionado
- **Fase 12:** Adaptadores para Discord, Slack e E-mail (IMAP IDLE + SMTP)
- Migration `013_channel_messages.sql`
- Comandos inline `/approve`, `/deny`, `/status` em todos os canais
- Rate limiting global e por canal
- Redação de segredos em logs

### Segurança
- Allowlists obrigatórias em todos os canais (sem allowlist, adapter não sobe)
- Anti-spoofing em E-mail
- Threading isolado por sessão

---

## [0.11.0] — 2026-05-05 — Web Dashboard

### Adicionado
- **Fase 11:** Web Dashboard com 8 painéis (chat, missões, skills, memória, traces, crítico, subagentes, aprovações)
- WebSocket multiplexado para atualizações em tempo real
- Auth token + CSP headers
- 113 testes (87% cobertura)
- Migration `012_web.sql`

---

## [0.10.0] — 2026-05-01 — Deploy Production-Ready

### Adicionado
- **Fase 10:** Supervisor + workers, health endpoints
- 12 métricas Prometheus
- Scripts de backup/restore
- Systemd install scripts
- Migration `011_deploy.sql`
- 106 testes

---

## [0.9.0] — 2026-04-25 — Skills Voyager-style

### Adicionado
- **Fase 9:** Skills auto-geradas com promoção estilo Voyager
- `SkillRegistry`, `SkillValidator`, `SkillSynthesizer`, `SkillPromoter`
- `SkillDecayManager` para degradar skills pouco usadas
- Migration `010_skills.sql`
- 72 testes

---

## [0.8.0] — 2026-04-20 — Sandboxes

### Adicionado
- **Fase 8:** Execução isolada via subprocess ou Docker
- `SubprocessBackend`, `DockerBackend`
- Políticas: `POLICY_READONLY`, `POLICY_STANDARD`, `POLICY_NETWORK`
- Tool `exec_tool` para execução genérica
- Migration `009_sandbox_executions.sql`
- 80 testes

### Corrigido
- `CancelledError` em `exec_tool` finally (prevenia `NameError`)
- Validação `NetworkPolicy.OPEN`
- `asyncio.get_running_loop` ao invés de `get_event_loop` (deprecated)

---

## [0.7.0] — 2026-04-15 — Missões + Crítico

### Adicionado
- **Fase 7:** Missões persistentes com state machine
- `MissionPlanner` com replanejamento automático
- `MissionReflector` com 4-campos rígidos
- `Critic` com 3 personas em `asyncio.gather`
- `ReflexiveMemory` com pgvector VECTOR(384)
- `AutonomousLoop` (tick a cada 5min)
- Migration `008_missions_critic.sql`
- 27 novos testes

---

## [0.6.0] — 2026-04-10 — Cron + Subagentes

### Adicionado
- **Fase 6:** APScheduler com persistência em Postgres
- NL → cron via LLM + croniter double-validation
- `TaskStore` + `SubagentPool` com isolamento por construção
- `Orchestrator` com tiers INSTANT/FAST/STRATEGIC/EPIC
- Tool `delegate` builtin
- Migration `007_cron_tasks.sql`
- CLI `agent cron/task`
- 74 novos testes

---

## [0.5.0] — 2026-04-05 — Gateway + Telegram

### Adicionado
- **Fase 5:** Gateway Node em TypeScript com Telegraf
- `ApprovalManager` com tabela `pending_approvals`
- `ApprovalScheduler` (expiração 30min default)
- `OutboundDispatcher` (Redis) + `OutboundWorker` (Bottleneck rate limiter)
- Allowlist de chat_ids
- Migrations `005_pending_approvals.sql` + `006_conversation_session_id.sql`
- 15 testes Python + 20 testes TypeScript

---

## [0.4.0] — 2026-04-01 — Multi-modelo

### Adicionado
- **Fase 4:** Transport Protocol unificado
- Transports: Anthropic, OpenAI, OpenRouter, Ollama
- `ModelRouter` com resolução `provider:model` e fallback chain
- Capability check via `/api/show` (Ollama)
- Migration `004_model_invocations.sql` (custo/latência/tokens)
- CLI `agent model list/health/show/test/costs`

---

## [0.3.0] — 2026-03-25 — Skills

### Adicionado
- **Fase 3:** `SkillManager` (loader + registry + match semântico)
- `SkillRunner` (Jinja2 + tool calls)
- `SkillCreator` (extração de sessão → draft)
- 4 skills builtin
- Migration `003_skill_invocations.sql`
- CLI `agent skill list/show/run/validate/review/create-from-session`

---

## [0.2.0] — 2026-03-20 — Memória Persistente

### Adicionado
- **Fase 2:** `MemoryStore` com pgvector + FTS multilingual
- Busca híbrida via RRF (Reciprocal Rank Fusion)
- `Curator` (Haiku) decidindo o que persistir
- `ContextCompressor` para histórico longo
- Tools `salvar_memoria` e `ler_memoria`
- Migration `002_memory_schema.sql`

---

## [0.1.0] — 2026-03-15 — Core Mínimo

### Adicionado
- **Fase 1:** `AIAgent` com loop ReAct
- Tools builtin: `read_file`, `write_file`, `list_dir`, `shell`, `web_search`
- CLI básica via Typer + Rich
- Transport Anthropic
- Sistema de eventos (`AgentEvent`)
- Configuração via `config.yaml` + env vars

---

## [0.0.0] — 2026-03-10 — Fundação

### Adicionado
- **Fase 0:** Estrutura inicial do projeto
- Docker Compose com Postgres + pgvector + Redis
- Dockerfile Python multi-stage
- Dockerfile Node multi-stage
- Estrutura de diretórios (core/, gateway/, cli/, config/, docs/)
- `SOUL.md`, `AGENTS.md`, `TOOLS.md`
- `pyproject.toml` (core + cli)
- `package.json` (gateway)

---

[Unreleased]: https://github.com/engsathiago/EVE_Autonomo/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.13.0
[0.12.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.12.0
[0.11.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.11.0
[0.10.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.10.0
[0.9.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.9.0
[0.8.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.8.0
[0.7.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.7.0
[0.6.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.6.0
[0.5.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.5.0
[0.4.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.4.0
[0.3.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.3.0
[0.2.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.2.0
[0.1.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.1.0
[0.0.0]: https://github.com/engsathiago/EVE_Autonomo/releases/tag/v0.0.0
