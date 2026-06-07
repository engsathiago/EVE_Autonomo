# Changelog

Todas as mudanças notáveis neste projeto serão documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [1.0.0] — 2026-06-01 — Primeira Release Estável

### Fases validadas em runtime

| Fase | Descrição | Status |
|------|-----------|--------|
| F0 | Fundação (estrutura, Docker, CI) | ✅ runtime |
| F1 | Core ReAct (AIAgent, tool loop, tool registry) | ✅ runtime |
| F2 | Memória pgvector (MemoryStore, Curator, ContextCompressor) | ✅ runtime |
| F3 | Skills (SkillManager, SkillRunner, 4 builtins) | ✅ runtime |
| F4 | Multi-modelo (Anthropic, OpenAI, OpenRouter, Ollama) | ✅ runtime |
| F7 | Critic + Missões (3 personas, MissionStore, AutonomousLoop) | ✅ runtime |
| F8 | Sandboxes (SubprocessSandbox + DockerSandbox, 5 perfis) | ✅ runtime |
| F9 | Voyager skill synthesis (SkillSynthesizer, cluster scan) | ✅ runtime |
| F11 | Web UI (8 painéis terminal, WebSocket, auth token) | ✅ runtime |
| Infra | CI GitHub Actions, auto-migrations, Dockerfile completo | ✅ runtime |

### Parciais

- **F5** — Gateway funcional; webhook Telegram retorna 404 ([#3](https://github.com/engsathiago/EVE_Autonomo/issues/3))
- **F6** — Importa OK; testes E2E requerem Anthropic/Ollama configurados
- **F10** — docker-compose.prod.yml adicionado nesta release

### Deferidas para v1.1

- **F12** — Canais extras Discord/Slack/Email ([#6](https://github.com/engsathiago/EVE_Autonomo/issues/6))
- **F13** — Ciclo LoRA real end-to-end ([#7](https://github.com/engsathiago/EVE_Autonomo/issues/7))

### Adicionado

- `docker-compose.prod.yml` — compose de produção com nginx, restart always, AUTO_MIGRATE
- `agent.db.migrate` — auto-migrations idempotentes com stamp_all para bootstrap
- CLI `agent db migrate [--dry-run] [--stamp]`
- `docs/ARCHITECTURE.md`, `docs/DEPLOY.md`, `docs/SECURITY.md` reescritos
- Webui: `scripts/run_webui.py` para desenvolvimento local na porta 8080

### Corrigido

- OllamaTransport `_build_headers()` + normalização `api_key=""→None`
- `MISSIONS_PLANNER_MODEL/REFLECTOR_MODEL` env vars lidas em `Settings.from_yaml()`
- Mocks de MissionStep com `tools_required=[]` (Pydantic v2 não expõe via spec)
- Fixture `invalid_tools_py/tools.py` estava vazia
- AutonomousLoop: mocks com `AgentResult` real + tool_calls_made

### Métricas

- **1158 testes passando**, 0 falhas
- Cobertura: 30%+ (target → 60% em v1.1)
- Migrations: 16 arquivos SQL

### Bugs em aberto

- [#1](https://github.com/engsathiago/EVE_Autonomo/issues/1) ALTO: OllamaTransport não callable via ModelRouter (workaround: template fallback)
- [#2](https://github.com/engsathiago/EVE_Autonomo/issues/2) ALTO: needs_critic() nunca retorna True no AutonomousLoop
- [#3](https://github.com/engsathiago/EVE_Autonomo/issues/3) MÉDIO: webhook /webhook/telegram retorna 404
- [#4](https://github.com/engsathiago/EVE_Autonomo/issues/4) MÉDIO: AGENT_NO_WEB=1 workaround Starlette lifespan
- [#5](https://github.com/engsathiago/EVE_Autonomo/issues/5) MÉDIO: SkillSynthesizer não persiste candidates automaticamente

---

## [1.1.0] — 2026-06-07 — Ollama Cloud default + Critic wire + Runtime validation

### Adicionado

- Provider `ollama_cloud` como default do ModelRouter (`DEFAULT_MODEL=ollama_cloud:deepseek-v3.1:cloud`)
- `OllamaCloudTransport` separado do `OllamaTransport` local — auth Bearer via `OLLAMA_CLOUD_API_KEY`
- Critic gate em skills irreversíveis em `AIAgent._execute_tools` (artigo A.3 do SECURITY.md — KI-1 fechado)
- Settings dedicados por componente LLM: `OrchestratorSettings.classifier_model`, `CriticSettings.medium_model` / `primary_model`, `MissionsSettings.planner_model` / `reflector_model`
- **Runtime validation framework** — marker `runtime` no `pyproject.toml`, fixtures asyncpg, testes em `tests/runtime/`
- 18 testes runtime cobrindo F5 / F6 / F7 / F8 / F9 / F11 (todos passando com Postgres real)
- `scripts/install_vps.sh` — instalação idempotente em VPS Ubuntu 22.04 via Docker Compose
- `migration/017_blocked_by_critic.sql` — status `blocked_by_critic` + índice parcial em `critic_evaluations(mission_id)`
- Documentos de Sprint 2: `AUDIT_REPORT.md`, `PLAN.md`, `DEPLOY_GAP.md`, `RUNTIME_VALIDATION_REPORT.md`, `BUG_F5_DISCOVERED.md`, `BUG_F11_DISCOVERED.md`, `SPRINT_2_REPORT.md`
- `docs/RUNTIME_TESTING.md` — guia do padrão de runtime testing para fases futuras

### Corrigido

- **BUG_F5-A:** `ApprovalManager.create()` agora serializa `skill_args` e `channel_ref` com `json.dumps` antes do `INSERT` em colunas `jsonb` (asyncpg rejeitava `dict` Python direto)
- **BUG_F5-B:** `ApprovalManager.get()` / `decide()` / `list_pending()` agora desserializam corretamente `UUID→str` e `jsonb str→dict` via helper `_row_to_state` (Pydantic rejeitava os tipos brutos)
- Critic conectado ao mission flow — antes da v1.1.0 estava registrado mas nunca era invocado em `core.py` (KI-1)
- `Settings.from_yaml()` agora parseia bloco `critic:` do `config.yaml` (antes era ignorado silenciosamente)
- `SubagentPool` agora propaga `db_pool` corretamente até o `AIAgent` dos subagentes — antes `critic_evaluations` não persistiam em subagentes (d4-critic fix)
- `tool_router.py` usa `model_router.default_model()` em vez de `anthropic:claude-haiku-4-5` hardcoded

### Alterado

- Hardcodes de modelo Anthropic removidos de `TierClassifier`, `Critic`, `MissionPlanner`, `MissionReflector` — agora leem de `Settings` com override via env var
- `config.yaml` default e `.env.example` apontam para `ollama_cloud` como provider principal; Anthropic vira fallback opcional via `MODEL_FALLBACK_CHAIN`

### Problemas conhecidos / Gaps

- **GAP-F11-A:** não existe endpoint REST `POST /api/ui/chat` — chat ocorre via WebSocket (`chat.send` op)
- **GAP-F11-B:** tabela `web_sessions` existe no schema mas o código nunca executa `INSERT` — sessions vivem em memória (`_WsSession`)
- **F12** (Discord/Slack/Email) e **F13** (LoRA finetune): código existe, runtime validation adiada para v1.2
- Repo contém dois venvs em `core/` (`.venv` incompleto, `.venv312` completo) — `install_vps.sh` consolida em um único
- Gateway healthcheck marca `unhealthy` durante restarts do Telegraf por `409 Conflict` (long-polling) — sugestão: migrar para webhook em produção
- `test_supervisor_internals.py::test_start_worker_sets_pid` falha em SQLite por DDL Postgres-specific (pré-existente, não introduzido nesta release)

### Métricas

- **18 testes runtime** adicionados (todos passando com Postgres real)
- **2 bugs F5** corrigidos
- **2 bugs KI** fechados (KI-1 Critic wire, KI-2 OllamaCloudTransport)
- **18 gaps** documentados em DEPLOY_GAP.md e RUNTIME_VALIDATION_REPORT.md

---

## [Unreleased]

### Corrigido
- **README.md:** roadmap agora reflete status real das fases (✅/⚠️/🔬/🚧/⏳) em vez de tudo ✅ independente de evidência de runtime
- **Badge de status:** trocado de "active" para "em desenvolvimento" — mais honesto dado que ~64% das fases são teóricas

### Adicionado
- **`docs/audit/PHASE_STATUS.md`:** verdade auditada de cada fase — VALIDADA, PARCIAL, TEÓRICA, EM ANDAMENTO
- **`docs/audit/EXECUTION_AUDIT.md`:** movido da raiz para `docs/audit/`
- **`docs/known-issues.md`:** 6 issues conhecidos documentados sem correção prematura
- **`docs/phases/FASE_D_BACKLOG.md`:** movido da raiz para `docs/phases/`
- **`docs/archive/hermes-debris/`:** pasta para artefatos históricos de sessões automatizadas

### Removido
- `cli/pyproject.toml.bak` e `cli/src/cli/skills.py.bak` — backups rastreados por engano
- `docker-compose.d5.yml` da raiz — movido para `docs/archive/hermes-debris/` (compose de validação D5 com senha hardcoded)
- `BUG_PATTERN_MAP.md` do tracking do git — relatório gerado, agora listado no `.gitignore`

---

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

[Unreleased]: https://github.com/engsathiago/EVE_Autonomo/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/engsathiago/EVE_Autonomo/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/engsathiago/EVE_Autonomo/compare/v0.13.0...v1.0.0
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
