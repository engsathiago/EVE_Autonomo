# FASE INFRA — CI + Auto-Migrations

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-f11-done`.

## Objetivo único

Suite de testes rodando em GitHub Actions (Docker matrix) + migrations Postgres aplicadas automaticamente no boot. Sem isso, deploy VPS é roleta russa.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **CI roda em PR e em push pra main.** Não é cosmético.
3. **Migrations rodam em ordem numérica** (001, 002, ..., 017). Migração que já rodou nunca roda 2x.
4. **NUNCA aplica DROP automático.** Migrations destrutivas exigem flag explícita.
5. **Secrets em GitHub Actions Secrets**, não no YAML.

## Passos

### 1. Auto-migrations

Cria `core/src/agent/db/migrate.py`:

```python
"""Aplica migrations em ordem, idempotente."""
import asyncio
import logging
from pathlib import Path
import asyncpg

MIGRATIONS_DIR = Path(__file__).parent.parent.parent.parent / "migrations"
LOG = logging.getLogger(__name__)

CREATE_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(10) PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    checksum VARCHAR(64)
);
"""

async def apply_migrations(dsn: str) -> list[str]:
    """Aplica migrations pendentes. Retorna lista de versões aplicadas."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(CREATE_TRACKING)
        applied = {row['version'] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        new = []
        for f in files:
            version = f.stem.split("_")[0]  # "001_initial.sql" -> "001"
            if version in applied:
                continue
            sql = f.read_text()
            checksum = _sha256(sql)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES($1, $2)",
                    version, checksum,
                )
            LOG.info("applied migration %s", version)
            new.append(version)
        return new
    finally:
        await conn.close()

def _sha256(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()
```

Plugar no boot do core. Em `core/src/agent/main.py` (ou onde inicializa):

```python
from agent.db.migrate import apply_migrations
import os

async def boot():
    if os.getenv("AUTO_MIGRATE", "true").lower() == "true":
        applied = await apply_migrations(os.environ["DATABASE_URL"])
        if applied:
            LOG.warning("applied %d new migrations: %s", len(applied), applied)
```

CLI command:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -m agent.cli db migrate --dry-run
PYTHONPATH=core/src ./.venv312/bin/python -m agent.cli db migrate
```

Testes em `core/tests/unit/test_migrate.py`:
- Tabela de tracking criada na primeira run
- Migration nova é aplicada
- Migration já aplicada não roda 2x
- Erro em migration faz rollback e não marca como aplicada
- Checksum diferente da já aplicada gera warning (não erro fatal)

### 2. GitHub Actions

Cria `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  core-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: agent
          POSTGRES_PASSWORD: agent
          POSTGRES_DB: agent_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: install
        run: |
          cd core
          python -m venv .venv
          .venv/bin/pip install -e .
          .venv/bin/pip install pytest pytest-asyncio pytest-mock pytest-cov
      - name: apply migrations
        env:
          DATABASE_URL: postgres://agent:agent@localhost:5432/agent_test
        run: |
          cd core
          PYTHONPATH=src .venv/bin/python -m agent.cli db migrate
      - name: run tests
        env:
          DATABASE_URL: postgres://agent:agent@localhost:5432/agent_test
          REDIS_URL: redis://localhost:6379
        run: |
          cd core
          PYTHONPATH=src .venv/bin/python -m pytest --cov=src --cov-report=term --tb=short

  gateway-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd gateway && npm ci && npm test

  web-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: cd web && npm ci && npm run build

  docker-build:
    runs-on: ubuntu-latest
    needs: [core-tests, gateway-tests, web-build]
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f docker-compose.yml config
      - run: docker compose -f docker-compose.prod.yml config
```

### 3. Boot script da prod

Cria `scripts/boot-prod.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "[boot] aguardando postgres..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -U "${POSTGRES_USER:-agent}" >/dev/null 2>&1; do
  sleep 1
done

echo "[boot] aplicando migrations..."
PYTHONPATH=src python -m agent.cli db migrate

echo "[boot] iniciando agente..."
exec python -m agent.cli serve
```

Aponta `Dockerfile` de produção pra esse script via `CMD ["bash", "/app/scripts/boot-prod.sh"]`.

### 4. Cobertura mínima

Adiciona em `pyproject.toml` ou `pytest.ini`:

```ini
[tool.coverage.report]
fail_under = 50
```

Se a cobertura atual está em 33%, sobe alvo gradualmente: 40% nesta fase, mira 60% nas próximas.

Se 50% é inalcançável agora → fail_under = 40 e documenta plano de subida em `RELATORIO_INFRA.md`.

### 5. Badges no README

Adiciona ao topo do `README.md`:

```markdown
![CI](https://github.com/engsathiago/EVE_Autonomo/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/badge/coverage-XX%25-blue)
```

### 6. Commit + tag + push

```bash
git add -A
git commit -m "feat(infra): CI + auto-migrations

- agent.db.migrate aplica SQL em ordem com tracking idempotente
- GitHub Actions: core tests, gateway tests, web build, compose validate
- Boot script de produção aplica migrations antes de servir
- Cobertura mínima 40% (subindo)

Desbloqueia: deploy VPS confiável"

git tag fase-infra-done
git push origin main --tags
```

CI VAI rodar imediatamente no push. Aguarda 5min e confirma no GitHub Actions que ficou verde.

### 7. Relatório

`RELATORIO_INFRA.md`:
```markdown
# Relatório Fase Infra
- [x] Auto-migrations integradas no boot
- [x] CI passando em main (link do run)
- Cobertura atual: __%
- Bugs encontrados: [lista]
- Próximo: 07_FASE_F13_lora_cycle.md
```

## Critério de aceite

- CI verde no GitHub Actions
- `db migrate --dry-run` mostra migrations pendentes
- Boot da prod chama migrate antes de servir
- Cobertura ≥ 40%
- Tag `fase-infra-done`

## Se CI falhar

- Bug isolado → conserta, push, espera novo run
- Bug fundamental (ex: testes dependem de serviço externo) → marca esses testes como `@pytest.mark.skip(reason="external dependency")` com TODO, documenta em `BUGS_ENCONTRADOS_INFRA.md`
- Se travar mais de 30min → tag `fase-infra-partial`, segue

## NÃO faça

- Não desliga teste pra fazer CI passar. Ou conserta, ou skip explícito com motivo.
- Não usa `secrets` no YAML — só `${{ secrets.X }}`.
- Não pergunta nada.
