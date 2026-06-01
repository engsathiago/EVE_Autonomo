# Decisões — Fase Cleanup

## VPS antiga (72.61.44.253)

**Status:** Host key SSH mudou — servidor provavelmente foi re-imaged pelo provider.
Conexão bloqueada por proteção de MITM do SSH client.

**Decisão:** Não tentar conectar à VPS antiga sem validação do fingerprint real.
Deploy VPS real será feito como operação separada pós-release usando docker-compose.prod.yml.

**Risco:** Nenhum — não havia dados críticos na VPS antiga (era um ambiente de teste).
O compose.prod.yml criado nesta fase serve como referência para o próximo deploy.

## docker-compose.prod.yml

Criado a partir do docker-compose.yml com ajustes de produção:
- `restart: always` em todos os serviços
- Portas internas apenas (sem exposição direta de DB/Redis ao host)
- `AUTO_MIGRATE=true` — migrations rodam automaticamente no boot
- `AGENT_LOG_JSON=true` — logging estruturado
- Target `runtime` em vez de `dev` no Dockerfile.python
- Volumes nomeados para persistência
- Healthchecks com `start_period` maior para boot lento em VPS fria

## Versão v1.0.0

Bump aplicado em core/pyproject.toml, cli/pyproject.toml, gateway/package.json.

## F12 e F13 — deferidos para v1.1

F12 (Discord/Slack/Email): adapters existem no core, falta wire no gateway Node.
F13 (LoRA real): infraestrutura completa, falta dataset ≥200 exemplos e budget GPU.
Não há bloqueadores técnicos — apenas recursos (tempo/dinheiro).
