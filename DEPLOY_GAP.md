# DEPLOY_GAP.md — Gap entre Scripts de Deploy e Instalação Real em VPS

**Data:** 2026-06-07  
**Branch:** docs/deploy-gap  
**Baseado em:** `docs/DEPLOY.md`, `docker-compose.prod.yml`, `deploy/digitalocean/deploy.sh`, `core/src/agent/deploy/install.py`

## Resumo executivo

A estratégia de deploy documentada usa **Docker Compose** (`docker-compose.prod.yml`).
O módulo Python `agent.deploy.install` implementa um install **systemd bare-metal** mas não
tem script de entrada (wrapper shell). Não existe nenhum script idempotente que execute
todos os passos do zero em uma VPS limpa.

`deploy/digitalocean/deploy.sh` é **placeholder** (apenas `echo` + `exit 0`).

---

## Tabela de gaps

| # | Passo | Script / Artefato | Instalado na VPS | Impacto |
|---|-------|-------------------|-----------------|---------|
| 1 | Instalar Docker Engine + Compose plugin | ❌ nenhum script | ❓ desconhecido | **ALTO** — sem Docker, compose falha completamente |
| 2 | Instalar git, curl, wget | ❌ nenhum script | ❓ desconhecido | **ALTO** — `git clone` na etapa 1 falha |
| 3 | Clonar repositório em `/opt/eve` | `DEPLOY.md` (manual) | ❓ desconhecido | **ALTO** — pré-requisito para tudo |
| 4 | Configurar `.env` com credenciais | `DEPLOY.md` (manual), `.env.example` | ❓ desconhecido | **ALTO** — core não sobe sem `ANTHROPIC_API_KEY` e `POSTGRES_PASSWORD` |
| 5 | `docker compose -f docker-compose.prod.yml up -d` | `DEPLOY.md` (manual) | ❓ desconhecido | MÉDIO — instrução existe mas não é automatizada |
| 6 | Aplicar migrations (`AUTO_MIGRATE=true`) | `docker-compose.prod.yml` env var | ✅ se compose rodou | BAIXO — automático no boot |
| 7 | Token da Web UI (`~/.agent/web_token`) | ❌ nenhum script | ❓ desconhecido | MÉDIO — Web UI inacessível sem token |
| 8 | Configurar UFW / firewall | ❌ nenhum script | ❓ desconhecido | **ALTO** — porta 3000 (gateway) exposta sem restrição |
| 9 | Nginx reverse proxy (HTTPS) | `DEPLOY.md` (mencionado, sem config) | ❓ desconhecido | MÉDIO — sem TLS, tráfego em claro |
| 10 | Cron de backup (`agent deploy backup`) | ❌ nenhum cron setup | ❌ ausente | MÉDIO — sem backup automático de dados |
| 11 | Logrotate | `core/src/agent/deploy/templates/logrotate.conf` (template) | ❓ desconhecido | BAIXO — logs crescem sem limite |
| 12 | Systemd install (bare-metal, sem Docker) | `agent deploy install` (Python) | ❌ deploy.sh é placeholder | **ALTO** — `deploy.sh` só faz echo+exit |
| 13 | Criação de usuário system `agent` | `core/src/agent/deploy/install.py` → `_create_user()` | ❓ desconhecido | MÉDIO — necessário para hardening systemd |
| 14 | Configurar `AGENT_NO_WEB=1` em prod | `docker-compose.prod.yml` env | ✅ no compose | INFO — workaround Starlette (issue conhecida) |
| 15 | sd_notify (watchdog systemd) | `core/src/agent/deploy/supervisor.py` | ❌ sem install systemd ativo | BAIXO — graceful shutdown funciona via SIGTERM |
| 16 | Healthcheck endpoints (`/live`, `/ready`) | `core/src/agent/deploy/health.py` | ✅ no processo | BAIXO — funcional se core sobe |

---

## Análise de impacto por categoria

### Crítico (bloqueiam instalação do zero)
- **#1 Docker** — sem Docker, nada funciona
- **#2 Sistema** — git/curl são pré-requisitos
- **#3 Repo** — repositório precisa existir antes de qualquer coisa
- **#4 .env** — sem credenciais o core não sobe
- **#12 deploy.sh placeholder** — o único ponto de entrada de deploy é um no-op

### Alto (comprometem segurança ou estabilidade)
- **#8 Firewall** — portas expostas sem restrição
- **#9 HTTPS** — sem TLS em produção

### Médio (degradam operação mas não bloqueiam)
- **#7 Web token** — Web UI inacessível
- **#10 Backup** — perda de dados em falha sem aviso
- **#13 Usuário system** — hardening systemd incompleto

### Baixo / informativo
- **#11 Logrotate** — template existe, precisa de copy manual
- **#15 sd_notify** — funcional em Docker via health probe
- **#16 Healthcheck** — funcional

---

## Artefatos existentes que PODEM ser usados

| Artefato | Localização | Estado |
|----------|-------------|--------|
| Compose de produção | `docker-compose.prod.yml` | ✅ funcional |
| `.env.example` | `.env.example` e `core/src/agent/deploy/templates/env.example` | ✅ existe |
| Install Python (systemd) | `core/src/agent/deploy/install.py` | ✅ funcional, precisa wrapper shell |
| Logrotate template | `core/src/agent/deploy/templates/logrotate.conf` | ✅ existe, precisa copy |
| Systemd unit template | `core/src/agent/deploy/templates/agent.service` | ✅ funcional, variáveis pendentes |
| Backup/restore | `agent deploy backup` / `agent deploy restore` | ✅ funcional via CLI |
| DEPLOY.md | `docs/DEPLOY.md` | ✅ cobre fluxo Docker, falta automação |

---

## O que D.2 (`scripts/install_vps.sh`) deve cobrir

Com base nos gaps identificados, o script deve:
1. Verificar e instalar dependências de sistema (Docker, git, curl)
2. Clonar o repo (idempotente — `git pull` se já existir)
3. Configurar `.env` a partir de `.env.example` (se não existir)
4. Configurar UFW básico (permitir 22, 80, 443, 3000, 8000 do localhost)
5. `docker compose up -d`
6. Gerar e salvar token da Web UI em `/etc/agent/web_token`
7. Instalar logrotate config
8. Opcional: configurar cron de backup diário
