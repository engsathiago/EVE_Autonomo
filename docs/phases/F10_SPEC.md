# F10 — Deploy & Operação 24/7

> Fase 10 do agente autônomo. Pré-requisito: F9 fechada na tag `phase-9-done`, com skills auto-geradas funcionando via `exec_tool` e suite verde.

---

## 1. Contexto

Até a F9 o agente roda na máquina de dev (`~/Desktop/agent`), em foreground, com o desenvolvedor olhando. A F10 é o que tira ele desse colo: empacotar, instalar, supervisionar, rotacionar logs, dar restart automático, expor health/metrics, e garantir que se a máquina reiniciar de madrugada o agente volta sozinho sem perder estado.

A F10 **não** é cloud. Continua local (workstation/homelab/VPS pessoal). Cloud é F10.1 se necessário.

A F10 **não** é Web UI. Web UI é F11. Aqui o operador interage por CLI, logs estruturados, e um endpoint `/health` + `/metrics`.

---

## 2. Objetivos

1. Rodar o agente como serviço gerenciado (systemd no Linux, launchd no macOS, NSSM no Windows — só systemd é obrigatório, os outros são best effort).
2. Restart automático em crash, com backoff exponencial e teto de tentativas.
3. Health check HTTP em `/health` com 3 níveis: liveness, readiness, deep.
4. Métricas Prometheus em `/metrics` cobrindo todos os componentes das F0–F9.
5. Logs estruturados (JSON) com rotação por tamanho e idade.
6. Backup automático do Postgres + SQLite + diretório `skills/` (snapshots diários, retenção 14 dias).
7. CLI `agent deploy` cobrindo install/uninstall/start/stop/restart/status/logs/backup/restore.
8. Smoke test pós-deploy: o agente sobe, atende `/health`, executa uma missão simples, sobrevive a um `kill -9` do worker e volta sozinho.

---

## 3. Não-objetivos (F10 NÃO faz)

- ❌ Deploy em cloud (AWS/GCP/Fly.io). Isso é F10.1.
- ❌ Container Kubernetes. Docker Compose é o teto.
- ❌ Multi-host / HA / replicação. É single-node.
- ❌ Web UI. F11.
- ❌ Auto-scaling. Não tem sentido em single-node.
- ❌ Secrets manager externo (Vault, AWS SM). Continua usando `.env` + permissões de arquivo.
- ❌ TLS automático. Se o operador quer expor publicamente, ele põe um Caddy/Nginx na frente.

---

## 4. Arquitetura do deploy

```
┌─────────────────────────────────────────────────────────┐
│  systemd (init)                                         │
│  └─ agent.service ─────────► supervisor.py             │
│                                  │                      │
│                                  ├─ orchestrator (F2)   │
│                                  ├─ scheduler (F6)      │
│                                  ├─ subagent_pool (F5)  │
│                                  ├─ api_server (F9)     │
│                                  └─ heartbeat            │
└─────────────────────────────────────────────────────────┘

Volumes persistidos:
  /var/lib/agent/data/        # SQLite, FTS, skills/_active/
  /var/lib/agent/state/       # mission state, checkpoints
  /var/lib/agent/logs/        # JSON logs rotacionados
  /var/lib/agent/backups/     # snapshots diários
  /etc/agent/                 # .env, config.toml

Endpoints expostos (loopback por padrão):
  http://127.0.0.1:8000/      # API F9
  http://127.0.0.1:8000/health
  http://127.0.0.1:8000/metrics
```

O `supervisor.py` é um processo Python que faz fork dos workers, monitora cada um, reinicia em crash, e propaga SIGTERM em shutdown. **Não** é o `multiprocessing.Pool` da F5 (esse continua pra subagentes). Esse é o supervisor do **processo do agente inteiro**.

---

## 5. Componentes novos

### 5.1 `agent/deploy/supervisor.py`

Processo pai. Fork-and-monitor de N workers (default 4: orchestrator, scheduler, api, heartbeat). Cada worker é uma classe que implementa `start()`, `stop()`, `is_alive()`. Supervisor:

- Faz `os.fork()` (Linux/macOS) ou `multiprocessing.Process` (Windows).
- Loop: a cada 5s checa `is_alive()`. Se morreu, restart com backoff (1s, 2s, 4s, 8s, 16s, 32s, 60s, depois 60s fixo).
- Após 10 restarts em 10 minutos no mesmo worker, manda alerta (evento `worker.flapping`) e desativa o worker até intervenção.
- Captura SIGTERM/SIGINT, propaga pros filhos com timeout de 30s, depois SIGKILL.
- Escreve PID no `/var/run/agent.pid` (ou path configurável).

### 5.2 `agent/deploy/health.py`

3 endpoints em FastAPI (estende o servidor da F9):

- `GET /health/live` — só responde 200. Liveness. systemd usa pra ver se o processo tá vivo.
- `GET /health/ready` — checa: SQLite acessível, Postgres acessível (se configurado), scheduler rodando, subagent_pool com pelo menos 1 worker. 200 se tudo ok, 503 se algo falhou.
- `GET /health/deep` — checa o do `ready` + executa uma skill `noop` real via `exec_tool` em sandbox SUBPROCESS, em <2s. Reporta latências de cada componente. 200/503.

### 5.3 `agent/deploy/metrics.py`

Endpoint `/metrics` no formato Prometheus. Métricas:

- `agent_missions_total{status="completed|failed|cancelled"}` (counter)
- `agent_mission_duration_seconds` (histogram)
- `agent_skills_executed_total{skill="<name>",result="success|failure"}` (counter)
- `agent_skill_execution_duration_seconds{skill="<name>"}` (histogram)
- `agent_subagent_pool_active` (gauge)
- `agent_sandbox_executions_total{profile="default|skill_dev|untrusted",result="ok|killed|timeout"}` (counter)
- `agent_critic_decisions_total{verdict="approve|reject|escalate"}` (counter)
- `agent_scheduler_jobs_active` (gauge)
- `agent_worker_restarts_total{worker="orchestrator|scheduler|api|heartbeat"}` (counter)
- `agent_db_query_duration_seconds{db="sqlite|postgres"}` (histogram)
- `agent_memory_bytes` (gauge, RSS do processo agent)
- `agent_uptime_seconds` (gauge)

### 5.4 `agent/deploy/logging.py`

Logger estruturado JSON. Cada linha é um JSON com `ts`, `level`, `component`, `mission_id?`, `worker?`, `msg`, `**extra`. Saída pra stdout (systemd captura) **e** pra arquivo rotacionado:

- Diretório: `/var/lib/agent/logs/`
- Arquivos: `agent.log` (atual), `agent.log.1.gz`, `agent.log.2.gz`, ...
- Rotação: 100MB por arquivo, 14 arquivos retidos, gzip nos antigos.

Logs sensíveis (chaves, tokens, prompts completos com PII) **nunca** vão pro log. Existe filtro no formatter que redacta padrões: `sk-...`, `Bearer ...`, `password=...`, telegram bot tokens.

### 5.5 `agent/deploy/backup.py`

Job no scheduler (F6) que roda diariamente às 4h da manhã:

1. `pg_dump` do banco Postgres → `/var/lib/agent/backups/postgres-YYYYMMDD.sql.gz`
2. `sqlite3 .backup` do SQLite → `/var/lib/agent/backups/sqlite-YYYYMMDD.db.gz`
3. `tar czf` do diretório `skills/_active/` → `/var/lib/agent/backups/skills-YYYYMMDD.tar.gz`
4. Apaga backups com mais de 14 dias.
5. Emite evento `backup.completed` com tamanhos e hashes SHA256.

Restore é manual via CLI: `agent deploy restore --date 20260301`.

### 5.6 `agent/deploy/systemd/agent.service`

Unit file template. Substituições via `agent deploy install`:

```ini
[Unit]
Description=Autonomous Agent (Thiago)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User={{USER}}
Group={{GROUP}}
WorkingDirectory={{INSTALL_DIR}}
EnvironmentFile=/etc/agent/.env
ExecStart={{INSTALL_DIR}}/.venv/bin/python -m agent.deploy.supervisor
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s
StartLimitInterval=600
StartLimitBurst=10
TimeoutStopSec=30
WatchdogSec=30
NotifyAccess=main

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agent /var/log/agent
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictNamespaces=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

O `Type=notify` requer que o supervisor mande `sd_notify(READY=1)` quando todos os workers subirem, e `WATCHDOG=1` a cada 10s. Isso dá ao systemd a capacidade de matar e reiniciar o agente se ele travar.

### 5.7 `agent/cli/deploy_cmd.py`

Novos subcomandos:

```
agent deploy install [--prefix /opt/agent] [--user agent] [--systemd]
agent deploy uninstall [--keep-data]
agent deploy start
agent deploy stop
agent deploy restart
agent deploy status                  # systemd status + health/ready + métricas-chave
agent deploy logs [--follow] [--since 1h] [--worker orchestrator]
agent deploy backup                  # dispara backup manual
agent deploy restore --date YYYYMMDD
agent deploy doctor                  # roda health/deep + checa permissões, paths, .env
agent deploy upgrade --to v0.10.x    # git pull + alembic upgrade + restart
```

Todos batem na API HTTP (F9) onde aplicável. `install/uninstall` exigem sudo se for systemd.

---

## 6. Persistência e migrações

Migration `010_deploy.sql` (idempotente):

```sql
CREATE TABLE IF NOT EXISTS deploy_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind        TEXT NOT NULL,        -- start|stop|crash|restart|backup|restore|upgrade
    worker      TEXT,                  -- orchestrator|scheduler|api|heartbeat|null
    detail      TEXT,                  -- JSON com contexto
    success     BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deploy_events_ts ON deploy_events(ts);
CREATE INDEX IF NOT EXISTS idx_deploy_events_kind ON deploy_events(kind);

CREATE TABLE IF NOT EXISTS worker_health (
    worker      TEXT PRIMARY KEY,
    pid         INTEGER,
    started_at  TIMESTAMP,
    last_seen   TIMESTAMP,
    restarts    INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL          -- running|stopped|flapping|disabled
);
```

---

## 7. Configuração

`/etc/agent/.env` (template em `agent/deploy/templates/env.example`):

```bash
# Database
AGENT_DB_SQLITE=/var/lib/agent/data/agent.db
AGENT_DB_POSTGRES_URL=postgresql://agent:***@localhost:5432/agent

# Paths
AGENT_DATA_DIR=/var/lib/agent/data
AGENT_STATE_DIR=/var/lib/agent/state
AGENT_LOG_DIR=/var/lib/agent/logs
AGENT_BACKUP_DIR=/var/lib/agent/backups
AGENT_SKILLS_DIR=/var/lib/agent/data/skills

# Server
AGENT_API_HOST=127.0.0.1
AGENT_API_PORT=8000

# Supervisor
AGENT_WORKERS=orchestrator,scheduler,api,heartbeat
AGENT_RESTART_MAX_PER_10MIN=10
AGENT_WATCHDOG_INTERVAL_SECONDS=10

# Logging
AGENT_LOG_LEVEL=INFO
AGENT_LOG_ROTATE_SIZE_MB=100
AGENT_LOG_RETAIN_FILES=14

# Backup
AGENT_BACKUP_HOUR=4
AGENT_BACKUP_RETAIN_DAYS=14

# LLM (continua igual F0)
ANTHROPIC_API_KEY=***
```

Permissões: `chmod 600 /etc/agent/.env`, dono `agent:agent`.

---

## 8. Eventos novos

Eventos emitidos no event bus (F4):

- `worker.started{worker, pid}`
- `worker.stopped{worker, exit_code, signal?}`
- `worker.restarted{worker, attempt, backoff_seconds}`
- `worker.flapping{worker, restarts_in_window}`
- `health.degraded{component, reason}`
- `health.recovered{component}`
- `backup.completed{kind, size_bytes, sha256, duration_ms}`
- `backup.failed{kind, error}`
- `restore.started{date, kinds}`
- `restore.completed{date, kinds, duration_ms}`
- `deploy.upgraded{from_version, to_version, migrations_applied}`

---

## 9. Estrutura de arquivos esperada

```
agent/
  deploy/
    __init__.py
    supervisor.py
    health.py
    metrics.py
    logging.py
    backup.py
    restore.py
    workers/
      __init__.py
      base.py                    # classe Worker(ABC)
      orchestrator_worker.py
      scheduler_worker.py
      api_worker.py
      heartbeat_worker.py
    templates/
      env.example
      agent.service              # systemd unit
      logrotate.conf             # alternativa se não usar Python rotation
    install.py                   # lógica do `agent deploy install`
  cli/
    deploy_cmd.py
  migrations/
    010_deploy.sql

tests/
  deploy/
    __init__.py
    conftest.py
    test_supervisor.py
    test_health.py
    test_metrics.py
    test_logging.py
    test_backup.py
    test_restore.py
    test_install.py
    test_workers.py
    test_e2e_deploy.py           # smoke real com systemd-user
```

---

## 10. Critérios de aceitação (C1–C10)

A F10 só fecha quando todos os 10 passam:

**C1.** `agent deploy install --systemd` numa VM/container limpo deixa o agente rodando, ouvindo em `127.0.0.1:8000`, com `systemctl status agent` reportando `active (running)`.

**C2.** Matar o worker `orchestrator` com `kill -9` faz o supervisor reiniciar ele em <10s, e emite evento `worker.restarted` com `attempt=1`.

**C3.** Matar o worker `orchestrator` 11 vezes em 10 minutos faz o supervisor emitir `worker.flapping` e marcar o worker como `disabled` em `worker_health`. Resto do agente continua respondendo.

**C4.** `GET /health/live` responde 200 em <50ms mesmo com o orchestrator travado num loop.

**C5.** `GET /health/ready` responde 503 quando o Postgres tá fora, e 200 quando volta. Sem manual restart.

**C6.** `GET /health/deep` executa uma skill `noop` real via `exec_tool` em sandbox SUBPROCESS e retorna em <2s com latências detalhadas por componente.

**C7.** `GET /metrics` retorna todas as 12 séries listadas em §5.3 no formato Prometheus, com valores não-zero pelo menos pras counters de boot.

**C8.** Backup automático às 4h cria 3 arquivos em `/var/lib/agent/backups/` (postgres, sqlite, skills tar) com SHA256 logado no evento `backup.completed`. Retenção de 14 dias funciona: arquivo de 15 dias atrás é apagado.

**C9.** `agent deploy restore --date <ontem>` derruba o agente, restaura os 3 backups, sobe de novo, e a contagem de missions completed é a mesma de antes do restore. Emite `restore.completed`.

**C10.** Reboot da máquina (real ou via `systemctl reboot`) faz o agente voltar sozinho em <60s do boot, com missões em estado `running` sendo retomadas ou marcadas como `interrupted` com motivo `host_reboot`.

---

## 11. Observabilidade mínima pós-deploy

Operador precisa conseguir, em <30s, responder:

- O agente tá rodando? → `agent deploy status` ou `systemctl status agent`
- O que ele tá fazendo agora? → `agent deploy logs --follow` ou `agent missions list --active`
- Tá saudável? → `curl localhost:8000/health/deep`
- Quantas missões fez hoje? → `curl localhost:8000/metrics | grep missions_total`
- Tem backup recente? → `ls -lh /var/lib/agent/backups/ | tail -5`
- Caiu nas últimas 24h? → `agent deploy logs --since 24h | grep '"kind":"worker.restarted"'`

---

## 12. Anti-padrões explicitamente proibidos

- ❌ Rodar como root. Usuário dedicado `agent`.
- ❌ Expor `/metrics` ou `/health` pra `0.0.0.0` por padrão. Loopback only.
- ❌ Logar prompts completos com PII ou chaves de API.
- ❌ Backup que bloqueia o agente. Tem que ser snapshot consistente (pg_dump em modo `--format=custom`, SQLite `.backup` API).
- ❌ Restart automático infinito sem backoff (causa fork bomb se o erro for determinístico).
- ❌ Health check que faz I/O pesado em `/live` (caro e quebra liveness probe).
- ❌ "Solução temporária" de rodar com `nohup` ou `tmux`. Ou é systemd, ou é Docker Compose, ou é launchd. Nada de processos órfãos.
- ❌ Vocabulário pomposo: `AgentDaemon`, `OmegaSupervisor`, `Sentinel`, `Vigil`. É `supervisor`, `worker`, `health`, `backup`.
- ❌ Upgrade que pula migration. `agent deploy upgrade` sempre roda `alembic upgrade head` antes do restart.
- ❌ Esconder erro de boot. Se um worker falha 10x seguidas no boot, o `Type=notify` nunca manda `READY=1` e o systemd marca como `failed`.

---

## 13. Fora de escopo (NÃO fazer na F10)

- **Deploy cloud** (AWS/GCP/Hetzner/Fly): F10.1.
- **Kubernetes / Helm chart**: nunca, projeto é single-node.
- **Métrica push** (StatsD, OTEL collector): F10.2 se necessário.
- **Alertmanager / PagerDuty**: F11 ou via Telegram bot já existente.
- **TLS terminado pela aplicação**: operador põe reverse proxy.
- **Multi-tenancy**: é um agente por host, ponto.

---

## 14. Entregáveis

- Branch `feature/phase-10-deploy`
- Tag `phase-10-done` quando C1–C10 passarem
- Suite de testes: `tests/deploy/` cobrindo cada critério
- Smoke E2E real numa VM Linux limpa (Ubuntu 24.04) ou container privilegiado com systemd
- Migration `010_deploy.sql` aplicada e idempotente
- Commit final: `feat(deploy): F10 - service supervisor, health, metrics, backup, systemd`
- Nenhuma dependência nova além de: `prometheus_client`, `python-systemd` (opcional, só linux), `psutil` se ainda não estiver. Justifica cada uma.

---

## 15. Notas de operação (vão pro README/docs)

- O agente é single-node por design. Pra ter "HA" verdadeira você precisaria de outra coisa (Postgres replicado, leader election, etc) — isso não tá no roadmap.
- Os backups são pra disaster recovery local, não pra time travel. Restaurar pula commits do skills/_active/ feitos depois do snapshot.
- A loopback-only é proposital. Se quiser acessar de outra máquina, ponha um SSH tunnel ou um reverse proxy (Caddy com `tls internal` é o mais fácil).
- O watchdog do systemd te protege contra deadlock no event loop, não contra bug semântico. Se o orchestrator entrar em loop infinito sem travar, o watchdog não dispara.
- `agent deploy doctor` é teu amigo. Roda ele depois de qualquer mudança de ambiente.
