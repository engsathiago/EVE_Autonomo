# Guia de Instalação

Este guia cobre todas as formas de instalar e executar a EVE.

## Opção 1: Docker Compose (recomendado)

A forma mais simples. Todos os serviços sobem com um comando.

### Pré-requisitos

- [Docker Engine](https://docs.docker.com/engine/install/) 24+
- [Docker Compose](https://docs.docker.com/compose/install/) v2+
- 4 GB de RAM livres (8 GB se usar Ollama)

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/seu-usuario/EVE_Autonomo.git
cd EVE_Autonomo

# 2. Crie e configure o .env
cp .env.example .env
```

Edite o `.env` com pelo menos:

```bash
ANTHROPIC_API_KEY=sk-ant-sua-chave-aqui
POSTGRES_PASSWORD=uma-senha-segura
```

```bash
# 3. Suba todos os serviços
docker compose up --build -d

# 4. Verifique
docker compose ps                    # Todos os serviços "healthy"
curl http://localhost:8000/health     # Core → {"ok": true}
curl http://localhost:3000/health     # Gateway → {"ok": true}
```

### Serviços que sobem

| Serviço | Porta | Descrição |
|---------|-------|-----------|
| `postgres` | 5432 | PostgreSQL 16 + pgvector |
| `redis` | 6379 | Redis 7 (pubsub + queue) |
| `core` | 8000 | Core Python (FastAPI) |
| `gateway` | 3000 | Gateway Node (Fastify + Telegram) |

### Com Ollama (modelos locais)

```bash
docker compose --profile local-llm up --build -d

# Depois, baixe um modelo
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

### Parando

```bash
docker compose down           # Para os containers
docker compose down -v        # Para e apaga volumes (dados do banco!)
```

---

## Opção 2: Desenvolvimento Local

Para quem quer mexer no código com hot-reload.

### Pré-requisitos

- Python 3.11+ (recomendado: 3.12)
- Node.js 20+
- PostgreSQL 16 com extensão pgvector
- Redis 7

### Infra via Docker (recomendado)

Suba só o Postgres e o Redis via Docker:

```bash
docker compose up postgres redis -d
```

### Core Python

```bash
cd core

# Criar e ativar virtualenv
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
# .venv\Scripts\activate        # Windows

# Instalar dependências
pip install -e ".[dev]"

# Configurar variáveis
export POSTGRES_URL="postgresql://agent:changeme@localhost:5432/agent"
export REDIS_URL="redis://localhost:6379/0"
export ANTHROPIC_API_KEY="sk-ant-..."

# Rodar com hot-reload
uvicorn agent.server:app --reload --port 8000
```

### Gateway Node

```bash
cd gateway

# Instalar dependências
npm install

# Configurar variáveis
export GATEWAY_CORE_URL="http://localhost:8000"
export REDIS_URL="redis://localhost:6379/0"
export TELEGRAM_BOT_TOKEN="seu-token-aqui"

# Rodar em desenvolvimento
npm run dev
```

### CLI

```bash
cd cli
pip install -e .

# Testar
agent --version
agent setup
```

---

## Opção 3: Deploy em VPS

Para produção. Veja o script de deploy em `deploy/digitalocean/deploy.sh`.

### Requisitos da VPS

- Ubuntu 22.04+ ou Debian 12+
- 2+ vCPUs, 4+ GB RAM
- Docker e Docker Compose instalados
- Domínio apontando para o IP (opcional, para HTTPS)

### Deploy rápido

```bash
# Na VPS:
git clone https://github.com/seu-usuario/EVE_Autonomo.git
cd EVE_Autonomo
cp .env.example .env
# Edite .env com credenciais de PRODUÇÃO

docker compose up --build -d
```

---

## Variáveis de Ambiente

O `.env.example` documenta todas. Aqui estão as essenciais:

### Obrigatórias

| Variável | Exemplo | Descrição |
|----------|---------|-----------|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Chave da API Anthropic |
| `POSTGRES_URL` | `postgresql://agent:pw@postgres:5432/agent` | Conexão PostgreSQL |
| `REDIS_URL` | `redis://redis:6379/0` | Conexão Redis |

### LLM (ao menos um provider)

| Variável | Provider |
|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) |
| `OPENAI_API_KEY` | OpenAI (GPT) |
| `OPENROUTER_API_KEY` | OpenRouter (múltiplos modelos) |
| `OLLAMA_BASE_URL` | Ollama (local, gratuito) |

### Canais (opcionais)

| Variável | Canal |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Telegram |
| `DISCORD_BOT_TOKEN` | Discord |
| `SLACK_APP_TOKEN` + `SLACK_BOT_TOKEN` | Slack |
| `EMAIL_USER` + `EMAIL_PASS` | E-mail |

### Segurança

| Variável | Descrição |
|----------|-----------|
| `TELEGRAM_ALLOWED_CHAT_IDS` | CSV de chat_ids autorizados no Telegram |
| `DISCORD_USER_ALLOWLIST` | CSV de user_ids autorizados no Discord |
| `SLACK_USER_ALLOWLIST` | CSV de member_ids autorizados no Slack |
| `EMAIL_FROM_ALLOWLIST` | CSV de endereços de e-mail autorizados |
| `ADMIN_USER_ID` | ID do administrador principal |

---

## Migrações de Banco

As migrações SQL em `core/migrations/` são aplicadas automaticamente quando o container do Postgres inicia pela primeira vez (via `docker-entrypoint-initdb.d`).

Para aplicar manualmente em um banco existente:

```bash
# Dentro do container
docker compose exec postgres psql -U agent -d agent -f /docker-entrypoint-initdb.d/002_memory_schema.sql

# Ou localmente
psql $POSTGRES_URL -f core/migrations/002_memory_schema.sql
```

---

## Verificação

Após a instalação, verifique:

```bash
# Health checks
curl http://localhost:8000/health
curl http://localhost:3000/health

# Testar o agente via CLI
agent run "Olá, tudo bem?"

# Testar via API
curl -X POST http://localhost:8000/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Olá, tudo bem?"}'

# Web Dashboard (se habilitado)
# Abra http://localhost:8000 no navegador
```

---

## Troubleshooting

### Core não inicia

```bash
docker compose logs core
# Verifique se ANTHROPIC_API_KEY está configurada
# Verifique se Postgres está healthy
```

### Gateway não conecta ao Core

```bash
docker compose logs gateway
# Verifique se GATEWAY_CORE_URL aponta para http://core:8000
# Verifique se o Core está rodando
```

### Postgres com erro de pgvector

```bash
# A imagem pgvector/pgvector:pg16 já inclui a extensão
# Se estiver usando Postgres sem pgvector:
docker compose exec postgres psql -U agent -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Ollama sem modelos

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
# Aguarde o download (~4 GB)
```
