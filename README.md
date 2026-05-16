# Agente Autônomo Híbrido

> **Status:** Fase 0 completa — fundação estabelecida. Sem lógica de agente ainda.

Agente autônomo inspirado no Hermes Agent (Nous Research) e OpenClaw (Peter
Steinberger): loop ReAct + memória curada + skills auto-criadas + multi-canal.

## Quickstart

```bash
# 1. Clone e entre na pasta
git clone <repo-url> agent && cd agent

# 2. Configure o ambiente
cp .env.example .env
# Edite .env com sua ANTHROPIC_API_KEY e credenciais do Postgres

# 3. Suba tudo
docker compose up --build -d

# 4. Verifique
curl http://localhost:8000/health   # {"ok": true}
curl http://localhost:8001/health   # {"ok": true}
```

Para incluir o Ollama (modelos locais):
```bash
docker compose --profile local-llm up --build -d
```

## Stack

| Camada     | Tecnologia                              |
|------------|-----------------------------------------|
| Core       | Python 3.11 + FastAPI + asyncio         |
| Gateway    | Node 20 + TypeScript + Fastify          |
| Banco      | PostgreSQL 16 + pgvector                |
| Bus        | Redis 7                                 |
| Web UI     | HTML + vanilla JS (Fase 7)              |
| Deploy     | Docker Compose → DigitalOcean/Hetzner   |

## Estrutura

```
agent/
├── core/          # Python: AIAgent, memória, skills, tools
├── gateway/       # Node: canais de mensagem (Telegram, Discord, etc.)
├── webui/         # HTML/JS estático (Fase 7)
├── cli/           # Python CLI (`agent` command)
├── config/        # SOUL.md, AGENTS.md, TOOLS.md, config.yaml
├── deploy/        # Scripts de deploy (Fase 11)
└── docs/          # Arquitetura, guias e specs de fase
```

## Roadmap

| # | Fase                                 | Status       |
|---|--------------------------------------|--------------|
| 0 | Fundação                             | ✅ Completo  |
| 1 | Core mínimo (AIAgent + 3 tools + CLI)| A fazer      |
| 2 | Memória (PostgreSQL + pgvector)      | A fazer      |
| 3 | Skills (manager + criação automática)| A fazer      |
| 4 | Multi-modelo (OpenAI + Ollama)       | A fazer      |
| 5 | Gateway Node + Telegram              | A fazer      |
| 6 | Discord + WhatsApp + Slack           | A fazer      |
| 7 | Web UI (vanilla JS + SSE)            | A fazer      |
| 8 | Cron + Subagentes                    | A fazer      |
| 9 | Sandboxes (Docker + SSH)             | A fazer      |
|10 | Plugins + MCP                        | A fazer      |
|11 | Deploy (DigitalOcean/Hetzner)        | A fazer      |

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

## Configuração

Toda configuração sensível via `.env` (nunca commitado). Comportamento do
agente editável em `config/SOUL.md` e `config/AGENTS.md` sem redeployar.

Veja `docs/architecture.md` para a arquitetura completa.
