# Segurança — EVE_Autonomo

## Garantias implementadas

### Sandbox (F8)

5 perfis de isolamento para execução de código:

| Perfil | Filesystem | Rede | Uso |
|--------|-----------|------|-----|
| `UNTRUSTED` | Nenhum | Nenhuma | Código não validado |
| `SKILL_DEV` | Tmp only | Nenhuma | Desenvolvimento de skills |
| `DEFAULT` | Workspace | Domínios allowlist | Skills normais |
| `TRUSTED` | Workspace + tools | Ampla | Tools confiáveis |
| `OPEN` | Irrestrito | Irrestrita | Admin only |

- Execução via `exec_tool()` — ponto único de entrada (C7 compliant)
- NetworkPolicy com intercept real de conexões não autorizadas
- Timeout hard configurável por perfil
- Registro de todas as execuções em `sandbox_executions`

### Critic Gating (D.4, F7)

3 personas avaliam cada ação antes de executar:
- **Technical**: análise técnica de segurança
- **Devil's Advocate**: questiona viabilidade e riscos
- **Synthesizer**: veredito final (approve/reject/escalate)

Actions marcadas como `irreversible=True` na skill manifest são sempre avaliadas.
Veredito `escalate` → pede aprovação humana antes de prosseguir.

### Approval Flow (F5)

Ações de alto impacto passam por aprovação humana via Telegram/Web UI:
- Expiração configurável (default 30 min)
- Propagação async para subagentes
- Registro completo em `pending_approvals`

### Redação de Segredos (F12)

Structlog processor `redact_secrets` detecta e redige:
- API keys (`sk-*`, `Bearer *`, padrões comuns)
- Credenciais em environment variables

### Auth Web UI (F11)

- Token HMAC-SHA256 armazenado em `~/.agent/web_token` (chmod 600)
- Cache 5s para evitar I/O excessivo
- Comparação via `hmac.compare_digest` (constant-time, timing-attack safe)
- Rate limit: 60 req/s por endpoint
- CSP estrita (sem unsafe-eval, sem unsafe-inline)

### Auto-migrations (Infra)

- `apply_migrations()` usa transações — falha parcial é revertida
- Sem DROP automático — migrations destrutivas requerem revisão manual
- Tracking em `schema_migrations` com checksum SHA256

## Modelo de ameaça (resumido)

### Escopo de ameaça

O sistema assume execução em ambiente controlado (VPS privada ou localhost).
Não é um serviço público sem autenticação.

### Ameaças mitigadas

| Ameaça | Mitigação |
|--------|-----------|
| Execução de código arbitrário via skills | Sandbox + NetworkPolicy |
| Actions irreversíveis sem supervisão | Critic gating + approvals |
| Injeção via mensagens de canal | Allowlist de chat_ids por canal |
| Leak de secrets em logs | redact_secrets processor |
| Timing attacks na auth Web UI | hmac.compare_digest |
| Path traversal na Web UI | Verificação `.relative_to()` |
| SQL injection | asyncpg parameterized queries |

### Ameaças conhecidas / fora de escopo

| Ameaça | Status |
|--------|--------|
| Canal Telegram webhook 404 | Em aberto (#3) — usar long-polling |
| Discord/Slack/Email não testados em E2E | Deferido F12 (#6) |
| Ciclo LoRA não validado em runtime | Deferido F13 (#7) |
| Bypass de sandbox via Docker shared volumes | Não testado |
| needs_critic() não ativa no loop autônomo | Em aberto (#2) |

## Configuração segura recomendada

```bash
# .env mínimo seguro
POSTGRES_PASSWORD=$(openssl rand -base64 32)
AGENT_WEB_TOKEN=$(openssl rand -base64 32)
```

```yaml
# docker-compose.prod.yml já configura:
# - Portas DB/Redis não expostas ao host (apenas 127.0.0.1:8000)
# - AUTO_MIGRATE=true
# - AGENT_LOG_JSON=true
```

## Reportar vulnerabilidades

Abrir issue privada ou contatar diretamente via eng.sathiago@gmail.com.
