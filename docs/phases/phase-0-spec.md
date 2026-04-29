# Fase 0 — Fundação

> **Como usar:** Cole esse arquivo inteiro como primeira mensagem no Claude
> Code. Antes de começar, peça: "Antes de codar, me dê o plano detalhado.
> Não escreva código ainda." Aprove o plano, então deixe ele executar.

## Objetivo

Estabelecer a fundação do projeto: estrutura de pastas, ferramentas de build,
configuração base, Docker Compose, documentação inicial, e skills locais do
Claude Code. **Nada de lógica de agente ainda.**

Ao final dessa fase, `docker compose up` deve subir todos os serviços
(mesmo que ainda sejam stubs) sem erros.

## Entregas

### 1. Estrutura de pastas
Criar exatamente:
```
agent/
├── core/
│   ├── pyproject.toml
│   └── src/agent/__init__.py
├── gateway/
│   ├── package.json
│   ├── tsconfig.json
│   └── src/index.ts
├── webui/
│   ├── index.html
│   └── app.js
├── cli/
│   ├── pyproject.toml
│   └── src/cli/__init__.py
├── config/
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── TOOLS.md
│   └── config.yaml
├── deploy/
│   └── digitalocean/deploy.sh
├── docs/
│   ├── architecture.md  (já existe — não sobrescrever)
│   └── phases/
├── .claude/
│   ├── skills/
│   └── agents/
├── docker-compose.yml
├── Dockerfile.python
├── Dockerfile.node
├── .env.example
├── .gitignore
└── README.md
```

### 2. `core/pyproject.toml`

Dependências mínimas (poetry ou hatch — escolha hatch, mais simples):

```toml
[project]
name = "agent-core"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "asyncpg>=0.30",
  "redis>=5.2",
  "anthropic>=0.40",
  "httpx>=0.28",
  "structlog>=24.4",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "ruff>=0.8", "mypy>=1.13"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"
```

### 3. `gateway/package.json`

```json
{
  "name": "agent-gateway",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "test": "vitest"
  },
  "dependencies": {
    "fastify": "^5.0.0",
    "ioredis": "^5.4.0",
    "pino": "^9.5.0",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "tsx": "^4.19.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0"
  }
}
```

### 4. `gateway/tsconfig.json`

Strict mode, ESM, output em `dist/`.

### 5. Stubs funcionais

**`core/src/agent/__init__.py`** — só version.
**`core/src/agent/server.py`** — FastAPI com `/health` retornando `{"ok": true}`.
**`gateway/src/index.ts`** — Fastify com `/health` e conexão Redis testada.
**`webui/index.html`** — página vazia bonita com "Agent Web UI — soon".
**`cli/src/cli/main.py`** — CLI com `agent --version` e `agent setup` (stub).

### 6. `docker-compose.yml`

Serviços:
- `postgres` (postgres:16 com pgvector via imagem `pgvector/pgvector:pg16`)
- `redis` (redis:7-alpine)
- `core` (build de Dockerfile.python, expõe 8000)
- `gateway` (build de Dockerfile.node, expõe 8001)
- `ollama` (ollama/ollama, opcional, com profile `local-llm`)

Volumes nomeados pra postgres data e ollama models. Healthchecks em todos.

### 7. `Dockerfile.python` e `Dockerfile.node`

Multi-stage builds. Python: base slim, uv pra instalar deps, non-root user.
Node: alpine, build TS, runtime mínimo.

### 8. `.env.example`

```
# LLM
ANTHROPIC_API_KEY=sk-ant-xxxx
OPENAI_API_KEY=
OPENROUTER_API_KEY=

# Database
POSTGRES_USER=agent
POSTGRES_PASSWORD=changeme
POSTGRES_DB=agent
POSTGRES_URL=postgresql://agent:changeme@postgres:5432/agent

# Redis
REDIS_URL=redis://redis:6379/0

# Channels
TELEGRAM_BOT_TOKEN=
DISCORD_BOT_TOKEN=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=

# Security
ADMIN_USER_ID=
APPROVAL_TIMEOUT_SECONDS=120
```

### 9. `config/SOUL.md`

Template em branco com seções: Personalidade, Tom de voz, Linguagens,
Limites éticos, Estilo de resposta. Exemplo preenchido brevemente como guia.

### 10. `config/AGENTS.md`

Regras de comportamento operacional: quando confirmar antes de agir, como
lidar com erros, política de uso de memória.

### 11. `config/TOOLS.md`

Documentação das tools (vazio agora, populado nas próximas fases).

### 12. `config/config.yaml`

Use o exemplo em `docs/architecture.md` seção 5 como base. Apenas estrutura,
todos os valores via env vars.

### 13. `README.md`

Quickstart: como clonar, copiar .env, `docker compose up`. Status: "Fase 0
completa. Sem agente ainda — só fundação."

### 14. `.gitignore`

Padrão Python + Node + IDE + .env + `.agent/`.

### 15. Skills do Claude Code em `.claude/skills/`

Crie 3 skills:

**`add-tool.md`:**
```markdown
# Adicionar uma Tool nova ao agente

## Quando usar
Quando o usuário pedir "adicione uma tool de X" ou "crie uma ferramenta Y".

## Passos
1. Crie `core/src/agent/tools/builtin/{nome}.py`
2. Herde de `BaseTool` (em `tools/base.py`)
3. Defina `name`, `description`, `input_schema` (JSON Schema), `async execute()`
4. Registre em `core/src/agent/tools/registry.py` no `register_builtin()`
5. Documente em `config/TOOLS.md`
6. Crie teste em `core/tests/tools/test_{nome}.py`
7. Rode `pytest core/tests/tools/test_{nome}.py` pra confirmar

## Padrão
Veja `tools/builtin/web_search.py` como referência canônica.
```

**`add-channel.md`:**
```markdown
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
```

**`add-transport.md`:**
```markdown
# Adicionar um Transport (provider de LLM) novo

## Quando usar
Quando o usuário pedir suporte a um novo provider (Gemini, Mistral, etc.)

## Passos
1. Crie `core/src/agent/transports/{nome}.py`
2. Herde de `BaseTransport` (em `transports/base.py`)
3. Implemente `async chat(system, messages, tools, **kwargs)` retornando
   `{"text", "tool_calls", "raw"}`
4. Converta o formato de tools do Anthropic-style pro formato do provider
5. Registre em `transports/registry.py`
6. Adicione config em `config/config.yaml` em `providers.{nome}`
7. Crie teste mock em `core/tests/transports/test_{nome}.py`

## Padrão
Veja `transports/anthropic.py` como referência canônica.
```

### 16. Subagentes em `.claude/agents/`

**`core-builder.md`:**
```markdown
---
name: core-builder
description: Especialista em código Python do core do agente
model: sonnet
tools: [Read, Write, Edit, Bash]
---

Você é especialista em construir o core Python deste agente.

REGRAS:
- Toque APENAS em arquivos sob `core/`.
- Sempre use async/await pra IO.
- Sempre adicione type hints e docstrings.
- Sempre escreva teste correspondente em `core/tests/`.
- Use as skills em `.claude/skills/` quando aplicável.
- Antes de criar arquivo novo, verifique se padrão similar já existe.
```

**`gateway-builder.md`:**
```markdown
---
name: gateway-builder
description: Especialista em código TypeScript do gateway Node
model: sonnet
tools: [Read, Write, Edit, Bash]
---

Você é especialista em construir o gateway Node deste agente.

REGRAS:
- Toque APENAS em arquivos sob `gateway/`.
- TypeScript strict, ESM, sem `any` sem justificativa.
- Use Zod pra validação de input externo.
- Logs via Pino com contexto estruturado.
- Sempre escreva teste em `gateway/tests/` com vitest.
```

**`test-writer.md`:**
```markdown
---
name: test-writer
description: Escreve testes unitários e de integração
model: haiku
tools: [Read, Write, Edit, Bash]
---

Você escreve apenas testes. Nunca implementação.

REGRAS:
- Python: pytest + pytest-asyncio.
- TypeScript: vitest.
- Use mocks/fakes quando o teste tocar IO externo.
- Sempre teste o caminho feliz, um caso de erro, e um edge case.
- Não modifique código de produção; se um teste expõe bug, reporte.
```

## Critério de aceite

Após terminar, rode:

```bash
# Estrutura
find . -type d | head -50

# Build Python
cd core && uv pip install -e ".[dev]" && pytest --collect-only

# Build Node
cd gateway && npm install && npm run build

# Subir tudo
docker compose up --build -d
docker compose ps

# Verificar saúde
curl http://localhost:8000/health
curl http://localhost:8001/health
```

Todos devem responder `{"ok": true}`.

## Próxima fase

Fase 1 — Core mínimo. Implementação do `AIAgent` com Anthropic transport,
3 tools básicas (filesystem, shell, web_search), e CLI funcional.
