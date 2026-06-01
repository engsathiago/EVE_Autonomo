# Deploy — EVE_Autonomo

## Pré-requisitos

- Docker 24+ e docker compose plugin
- Git
- Domínio (opcional, para HTTPS via nginx reverse proxy)

## Quick Start (VPS)

### 1. Clonar e configurar

```bash
git clone https://github.com/engsathiago/EVE_Autonomo.git /opt/eve
cd /opt/eve

cp .env.example .env
chmod 600 .env
```

Edite `.env` com as variáveis obrigatórias:
```bash
ANTHROPIC_API_KEY=sk-ant-...        # Obrigatório para LLM
POSTGRES_PASSWORD=<senha_forte>      # ≥20 chars
TELEGRAM_BOT_TOKEN=...               # Para canal Telegram (opcional)
AGENT_WEB_TOKEN=<token_seguro>       # Para Web UI (opcional)
```

### 2. Subir em produção

```bash
docker compose -f docker-compose.prod.yml up -d

# Aguardar boot completo
sleep 30
docker compose -f docker-compose.prod.yml ps
```

### 3. Verificar saúde

```bash
# Core API
curl -f http://localhost:8000/health

# Gateway
curl -f http://localhost:3000/health

# Migrations
docker compose -f docker-compose.prod.yml exec core \
  python -c "from agent.db.migrate import apply_migrations; import asyncio; print(asyncio.run(apply_migrations('postgresql://agent:${POSTGRES_PASSWORD}@postgres:5432/agent')))"
```

### 4. Web UI (opcional)

O webui serve via nginx na porta 8080. Para acessar com HTTPS, configure um reverse proxy (Nginx/Caddy).

Para desenvolvimento local (sem Docker):
```bash
PYTHONPATH=core/src core/.venv/bin/python scripts/run_webui.py
# Abre http://localhost:8080/?token=<token>
```

## Atualizações

```bash
cd /opt/eve
git pull origin main

# Rebuild + restart
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# Migrations automáticas no boot (AUTO_MIGRATE=true)
# Ou manualmente:
docker compose -f docker-compose.prod.yml exec core \
  agent db migrate
```

## Troubleshooting

### Container core em restart loop

```bash
docker compose -f docker-compose.prod.yml logs core --tail=50
```

Causas comuns:
- `ANTHROPIC_API_KEY` ausente ou inválida → adicione ao `.env`
- `POSTGRES_PASSWORD` não bate com o DB existente → verifique `.env`
- Skills dir sem permissão → verifique volume `skills_data`

### Migrations não aplicaram

```bash
# Verifica pendentes
docker compose -f docker-compose.prod.yml exec core \
  agent db migrate --dry-run

# Aplica
docker compose -f docker-compose.prod.yml exec core \
  agent db migrate

# Bootstrap (DB sem schema_migrations)
docker compose -f docker-compose.prod.yml exec core \
  agent db migrate --stamp
```

### Web UI 404

Causas:
1. `AGENT_NO_WEB=1` no compose → webui desabilitado, use `scripts/run_webui.py`
2. `AGENT_WEBUI_DIR` não aponta para `webui/public` → verifique env var

### Gateway degraded (core unreachable)

```bash
# Verifica se core está healthy
docker compose -f docker-compose.prod.yml ps core

# Verifica conectividade interna
docker compose -f docker-compose.prod.yml exec gateway \
  wget -qO- http://core:8000/health
```

## Backup e restore

```bash
# Backup manual
docker compose -f docker-compose.prod.yml exec core \
  agent deploy backup

# Restore
docker compose -f docker-compose.prod.yml exec core \
  agent deploy restore /var/backups/agent/<arquivo>
```

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | — | **Obrigatório** para LLM |
| `POSTGRES_PASSWORD` | — | **Obrigatório** |
| `POSTGRES_USER` | `agent` | Usuário do banco |
| `POSTGRES_DB` | `agent` | Nome do banco |
| `REDIS_URL` | `redis://redis:6379/0` | URL do Redis |
| `AUTO_MIGRATE` | `true` | Aplica migrations no boot |
| `AGENT_LOG_JSON` | — | Logging estruturado JSON |
| `AGENT_NO_WEB` | `1` | Desabilita web module (workaround Starlette) |
| `AGENT_WEB_TOKEN` | — | Token para Web UI |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude |
| `OPENAI_API_KEY` | — | OpenAI (opcional) |
| `OPENROUTER_API_KEY` | — | OpenRouter (opcional) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama local |
| `TELEGRAM_BOT_TOKEN` | — | Bot Telegram (F5) |
