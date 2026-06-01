<p align="center">
  <strong>EVE — Agente Autônomo</strong>
</p>

<p align="center">
  <a href="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml">
    <img src="https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <img src="https://img.shields.io/badge/version-1.0.0-blue.svg" alt="v1.0.0" />
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/node-20%2B-green.svg" alt="Node 20+" />
  <img src="https://img.shields.io/badge/tests-1158%20passing-brightgreen.svg" alt="1158 tests" />
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT" />
</p>

<h1 align="center">EVE_Autonomo</h1>

<p align="center">
  Agente autônomo multi-modelo, multi-canal com memória persistente, skills auto-geradas,
  missões de longo prazo, sandboxes isoladas e fine-tuning local periódico.
</p>

---

## O que é

EVE é um sistema de agente IA completo que combina o melhor do [Hermes Agent](https://github.com/NousResearch/hermes-function-calling) (loop autônomo, memória curada, skills auto-criadas) com [OpenClaw](https://github.com/steipete/OpenClaw) (gateway multi-canal, config via SOUL.md, approvals).

**Stack:** Python 3.11 · FastAPI · PostgreSQL 16 + pgvector · Redis 7 · Node 20 · TypeScript

## Componentes

```
core/    Python — AIAgent, memória, skills, critic, missões, sandbox
gateway/ TypeScript — canais (Telegram), approvals, pub/sub Redis
webui/   HTML/JS vanilla — dashboard 8 painéis
cli/     Python Typer — 20+ subcomandos de controle
```

## Quick start (desenvolvimento local)

```bash
git clone https://github.com/engsathiago/EVE_Autonomo.git
cd EVE_Autonomo

cp .env.example .env
# Edite .env: ANTHROPIC_API_KEY=sk-ant-...

docker compose up -d
sleep 20

# Verifica saúde
curl http://localhost:8000/health   # core
curl http://localhost:3000/health   # gateway

# Web UI (em outro terminal)
PYTHONPATH=core/src core/.venv/bin/python scripts/run_webui.py
# Abre http://localhost:8080
```

## Quick start (produção VPS)

```bash
git clone https://github.com/engsathiago/EVE_Autonomo.git /opt/eve
cd /opt/eve

cp .env.example .env && chmod 600 .env
# Edite: ANTHROPIC_API_KEY, POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN

docker compose -f docker-compose.prod.yml up -d
```

Ver [docs/DEPLOY.md](docs/DEPLOY.md) para guia completo com troubleshooting.

## Status das fases

| Fase | Descrição | Status |
|------|-----------|--------|
| F0 | Fundação (estrutura, Docker, CI) | ✅ validada |
| F1 | Core ReAct (AIAgent, tool loop) | ✅ validada |
| F2 | Memória pgvector (MemoryStore, Curator) | ✅ validada |
| F3 | Skills (SkillManager, 4 builtins) | ✅ validada |
| F4 | Multi-modelo (Anthropic, OpenAI, Ollama) | ✅ validada |
| F5 | Gateway + Telegram | ⚠️ parcial (webhook 404) |
| F6 | Cron + Subagentes | ⚠️ parcial (LLM local) |
| F7 | Missões + Critic (3 personas) | ✅ validada |
| F8 | Sandboxes (5 perfis) | ✅ validada |
| F9 | Voyager skill synthesis | ✅ validada |
| F10 | Deploy VPS | ✅ compose.prod adicionado |
| F11 | Web UI dashboard | ✅ validada |
| F12 | Canais extras (Discord/Slack/Email) | ⏸️ v1.1 |
| F13 | Fine-tuning LoRA periódico | ⏸️ v1.1 |
| Infra | CI verde, auto-migrations | ✅ validada |

## CLI

```bash
pip install -e cli

agent --help          # lista todos os comandos
agent chat            # TUI interativo (alias: eve)
agent mission list    # missões ativas
agent skills list     # skills disponíveis
agent db migrate      # aplica migrations pendentes
agent deploy status   # status dos workers
agent web start       # inicia Web UI local
```

## Testes

```bash
cd core
pip install -e ".[dev]"
pytest -m "not integration" -q    # 1158 testes, ~27s
```

## Roadmap pós v1.0

- **v1.1:** F12 canais extras (Discord/Slack/Email) + F13 ciclo LoRA real
- **v1.x:** cobertura testes → 60%, RLAIF (F14)
- **Bugs abertos:** ver [Issues](https://github.com/engsathiago/EVE_Autonomo/issues)

## Documentação

| Documento | Conteúdo |
|-----------|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Diagrama de componentes, fluxo de missão, pontos de extensão |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Guia de deploy VPS + troubleshooting |
| [docs/SECURITY.md](docs/SECURITY.md) | Modelo de ameaça, sandbox, critic gating |
| [CHANGELOG.md](CHANGELOG.md) | Histórico de releases |

## Licença

MIT — ver [LICENSE](LICENSE).
