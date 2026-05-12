# Testes de Deploy (F10)

## Suite de testes

| Arquivo | Critérios | Tipo |
|---|---|---|
| `test_persistence.py` | C1 (pré-req) | unitário |
| `test_supervisor.py` | C2, C3 | unitário |
| `test_health.py` | C4, C5, C6 | unitário |
| `test_metrics.py` | C7 | unitário |
| `test_backup.py` | C8 | unitário |
| `test_restore.py` | C9 | unitário |
| `test_workers.py` | componentes | unitário |
| `test_logging.py` | redação de secrets | unitário |
| `test_install.py` | templates | unitário |
| `test_integration_events.py` | C2–C9 (eventos) | integração leve |
| `test_integration_api.py` | C4–C9 (HTTP) | integração leve |
| `test_e2e_deploy.py` | C1, C2, C3, C10 | `@pytest.mark.integration` |

## Rodando os testes unitários

```bash
cd core
source .venv312/bin/activate
pytest tests/deploy/ -v -m "not integration"
```

Tempo esperado: < 90 segundos.

## Cobertura

```bash
pytest tests/deploy/ --cov=agent/deploy --cov-report=term-missing -m "not integration"
```

Meta: ≥ 80% de cobertura em `agent/deploy/`.

## Rodando testes de integração (requer container privilegiado ou VM Linux)

Os testes marcados com `@pytest.mark.integration` precisam de systemd funcional.
Em macOS ou CI sem systemd eles são **pulados automaticamente** com `skipif`.

### Via Docker (Ubuntu 24.04 com systemd):

```bash
docker run --privileged --rm \
  -v $(pwd):/app \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  ubuntu:24.04 \
  bash -c "
    apt-get update -q && apt-get install -y python3 python3-pip python3-venv systemd
    cd /app/core
    python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    .venv/bin/pytest tests/deploy/ -v -m integration
  "
```

### Em VM Linux com systemd:

```bash
# 1. Instalar dependências
cd ~/Desktop/agent/core
source .venv312/bin/activate

# 2. Instalar como serviço (requer sudo)
cd ..
sudo python -m agent.deploy.install --prefix /opt/agent --user agent

# 3. Rodar testes E2E
pytest core/tests/deploy/test_e2e_deploy.py -v
```

## Critérios de aceitação mapeados

| Critério | Arquivo(s) | Descrição |
|---|---|---|
| **C1** | `test_e2e_deploy.py::TestInstallC1` + `test_install.py` | install → systemctl active |
| **C2** | `test_supervisor.py::TestFirstRestartC2` + `test_e2e_deploy.py::TestKillRestartC2` | kill -9 → restart em <10s |
| **C3** | `test_supervisor.py::TestFlappingDetectionC3` + `test_e2e_deploy.py::TestFlappingC3` | 11 kills → flapping |
| **C4** | `test_health.py::TestLiveness` + `test_integration_api.py::TestLivenessC4` | /live <50ms |
| **C5** | `test_health.py::TestPostgresC5` + `test_integration_api.py::TestReadinessC5` | 503 com PG down |
| **C6** | `test_health.py::TestDeepHealth` + `test_integration_api.py::TestDeepHealthC6` | /deep <2s com noop |
| **C7** | `test_metrics.py::TestMetricsBootC7` + `test_integration_api.py::TestMetricsC7` | 12 séries não-zero |
| **C8** | `test_backup.py::TestRunBackup` + `test_integration_api.py::TestBackupApiC8` | 3 arquivos + SHA256 |
| **C9** | `test_restore.py::TestRunRestore` + `test_integration_api.py::TestRestoreApiC9` | round-trip + evento |
| **C10** | `test_e2e_deploy.py::TestRebootRecoveryC10` | reboot → up em <60s |

## Notas

- `pg_dump` / `pg_restore` são sempre mockados nos testes unitários.
- `sqlite3.Connection.backup()` é testado com banco real (sem mock) — conforme especificação.
- Testes de sinal (`os.fork()` + `os.kill()`) rodam apenas em POSIX (Linux/macOS).
- `test_e2e_deploy.py` faz `os.fork()` para C2/C3 — não roda no Windows.
