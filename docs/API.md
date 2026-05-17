# Referência da API

A EVE expõe uma API REST via FastAPI no Core Python (porta 8000 por padrão).

---

## Health Check

```
GET /health
```

**Resposta:**
```json
{"ok": true}
```

---

## Mensagens

### Enviar mensagem

```
POST /v1/messages
```

**Body:**
```json
{
  "content": "Quais arquivos existem no workspace?",
  "conversation_id": "uuid-opcional",
  "model": "anthropic:claude-haiku-4-5"
}
```

**Resposta:**
```json
{
  "response": "Encontrei os seguintes arquivos...",
  "conversation_id": "abc-123",
  "iterations": 3,
  "total_input_tokens": 1250,
  "total_output_tokens": 340,
  "estimated_cost_usd": 0.0012,
  "duration_s": 2.4
}
```

---

## Aprovações

### Listar aprovações pendentes

```
GET /v1/approvals
```

**Resposta:**
```json
{
  "approvals": [
    {
      "id": "appr-001",
      "action": "shell",
      "params": {"command": "rm -rf /tmp/old"},
      "status": "pending",
      "created_at": "2026-05-17T10:00:00Z",
      "expires_at": "2026-05-17T10:30:00Z"
    }
  ]
}
```

### Aprovar/Negar operação

```
POST /v1/approvals/{approval_id}
```

**Body:**
```json
{
  "decision": "approve",
  "reason": "Pode deletar, são arquivos temporários"
}
```

`decision` aceita: `"approve"` ou `"deny"`.

---

## Cron (Agendamento)

### Criar job

```
POST /v1/cron/jobs
```

**Body:**
```json
{
  "description": "Checar PRs abertos",
  "schedule": "0 9 * * 1-5",
  "goal": "Verificar se há pull requests pendentes de review"
}
```

O campo `schedule` aceita cron expressions padrão. Também é possível usar linguagem natural — o agente converte automaticamente.

### Listar jobs

```
GET /v1/cron/jobs
```

### Obter job específico

```
GET /v1/cron/jobs/{job_id}
```

### Remover job

```
DELETE /v1/cron/jobs/{job_id}
```

### Executar agora

```
POST /v1/cron/jobs/{job_id}/run-now
```

---

## Missões

### Planejar missão (dry-run)

```
POST /v1/missions/plan
```

**Body:**
```json
{
  "goal": "Migrar o banco para o novo schema",
  "context": "Precisamos adicionar a tabela de audit_logs"
}
```

**Resposta:** retorna os steps planejados sem criar a missão.

### Criar missão

```
POST /v1/missions
```

**Body:**
```json
{
  "goal": "Migrar o banco para o novo schema",
  "context": "Precisamos adicionar a tabela de audit_logs"
}
```

### Listar missões

```
GET /v1/missions
```

### Obter missão

```
GET /v1/missions/{mission_id}
```

### Obter steps da missão

```
GET /v1/missions/{mission_id}/steps
```

### Replanejar missão

```
POST /v1/missions/{mission_id}/replan
```

### Refletir sobre missão

```
POST /v1/missions/{mission_id}/reflect
```

---

## Tasks

### Listar tasks

```
GET /v1/tasks
```

### Obter task

```
GET /v1/tasks/{task_id}
```

### Árvore de tasks

```
GET /v1/tasks/{task_id}/tree
```

Retorna a task e todas as sub-tasks (subagentes) em hierarquia.

### Cancelar task

```
POST /v1/tasks/{task_id}/cancel
```

### Estatísticas do orquestrador

```
GET /v1/tasks/orchestrator/stats
```

---

## Loop Autônomo

### Status

```
GET /v1/loop/status
```

**Resposta:**
```json
{
  "enabled": true,
  "running": true,
  "interval_minutes": 5,
  "last_tick": "2026-05-17T10:15:00Z",
  "total_ticks": 42,
  "steps_this_tick": 2
}
```

### Tick manual

```
POST /v1/loop/tick
```

### Pausar

```
POST /v1/loop/pause
```

### Retomar

```
POST /v1/loop/resume
```

---

## Crítico Autônomo

### Avaliações

```
GET /v1/critic/evaluations
```

Parâmetros de query:
- `limit` (int, default 20): máximo de resultados
- `offset` (int, default 0): paginação

### Estatísticas

```
GET /v1/critic/stats
```

### Teste (avaliar texto ad-hoc)

```
POST /v1/critic/test
```

**Body:**
```json
{
  "action": "Vou deletar todos os backups antigos",
  "context": "O disco está 95% cheio"
}
```

---

## Memória Reflexiva

### Listar insights

```
GET /v1/memory/reflexive
```

### Buscar insights

```
POST /v1/memory/reflexive/search
```

**Body:**
```json
{
  "query": "decisões sobre schema de banco",
  "limit": 5
}
```

### Remover insight

```
DELETE /v1/memory/reflexive/{insight_id}
```

---

## Web Dashboard API

Estas rotas servem o dashboard web (prefixo `/web/api/`).

### Missões

```
GET  /web/api/missions
POST /web/api/missions
GET  /web/api/missions/{id}
POST /web/api/missions/{id}/pause
POST /web/api/missions/{id}/resume
```

### Skills

```
GET  /web/api/skills
GET  /web/api/skills/{name}
POST /web/api/skills/{name}/disable
```

### Memória

```
POST /web/api/memory/search
```

**Body:**
```json
{
  "query": "como configurar o Telegram",
  "limit": 10
}
```

### Traces

```
GET /web/api/traces
GET /web/api/traces/{trace_id}
```

Parâmetros de query para listagem:
- `limit` (int): máximo de resultados
- `offset` (int): paginação
- `since` (datetime): filtrar por data

### Crítico

```
GET /web/api/critic/queue
GET /web/api/critic/history
```

### Subagentes

```
GET /web/api/subagents
```

### Aprovações

```
GET  /web/api/approvals
POST /web/api/approvals/{id}
```

### Métricas

```
GET /web/api/metrics/summary
```

**Resposta:** métricas consolidadas incluindo tokens, custo, latência, uptime.

### Sistema

```
GET /web/api/system/info
```

**Resposta:** versão, modelos configurados, providers ativos, status dos serviços.

### WebSocket

```
WS /api/v1/stream
```

WebSocket multiplexado para eventos em tempo real. Envia:
- Mensagens do agente (streaming)
- Atualizações de missões
- Novas aprovações pendentes
- Eventos do crítico
- Métricas em tempo real

**Autenticação:** envie o token no header `Authorization` ou como query param `?token=`.
