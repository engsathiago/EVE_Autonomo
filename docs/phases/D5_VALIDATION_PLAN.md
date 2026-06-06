# D5 — Plano de Re-validação F5–F13 em Runtime Real

> Branch: `validate/d5-runtime-revalidation`  
> DB de validação: `agent_d5_validation` (PostgreSQL isolado — produção intocada)  
> Modelo padrão: `anthropic:claude-haiku-4-5`  
> Limite de chamadas Anthropic: 200 na sessão inteira  
> Data: 2026-05-29

---

## Diagnóstico pré-validação (pré-requisitos confirmados)

| Item | Status |
|------|--------|
| Tag `phase-13-done` | ✓ presente |
| Tag `fase-b-done` | ✓ presente |
| Tag `d1-done` | ✓ presente |
| Branch `main`, working tree limpo | ✓ |
| Postgres + Redis + Core up | ✓ core healthy |
| Gateway status | ⚠ unhealthy (Redis reconnection periódica — mas operacional: status ok) |
| ANTHROPIC_API_KEY | ✓ presente |
| EXECUTION_AUDIT.md | ✓ em `./EXECUTION_AUDIT.md` |
| Migrations 015 + 016 | ✓ aplicadas no DB de validação |
| DB `agent_d5_validation` criado | ✓ 27 tabelas |
| Core rodando contra DB de validação | ✓ confirmado (`/v1/missions` retorna lista vazia) |

### Descoberta relevante: imagem Docker desatualizada

O container `agent-core-1` foi construído com `server.py` de **523 linhas** (pré-F11).
O source local tem **>680 linhas** (F11 adicionou `attach_web_routes`).
Consequência: o módulo `agent.web` não existe no container → rotas `/api/v1/*` retornam 404.

**Impacto no plano:** F11 requer rebuild da imagem antes de poder ser validado em runtime.
Rebuildaremos como parte do PASSO 3 para F11.

---

## Plano de validação por fase

### F5 — Gateway Node + Telegram (Approvals)

| Campo | Valor |
|-------|-------|
| **Missão** | Criar mensagem de saída via `/v1/messages` (POST) que força o gateway a publicar em `outbound:telegram` no Redis, e o OutboundWorker entrega ao Telegram bot |
| **Approach alternativo** | Postar mensagem diretamente no Redis `outbound:telegram` e verificar se OutboundWorker processa (sem depender de fluxo completo de missão) |
| **Critério positivo** | Linha em `outbound_messages_log` com `channel=telegram` e `status=delivered` OU `telegram_messages` com `direction=out`; gateway log mostra `telegram.send.ok` |
| **Critério negativo** | Nenhum HTTP 500 no gateway; gateway não crashar durante o teste |
| **Evidência** | `SELECT * FROM outbound_messages_log ORDER BY created_at DESC LIMIT 1` no DB de validação |
| **Tempo limite** | 60 segundos |
| **Modelo** | N/A — teste via API direta, sem LLM |
| **Observação** | TELEGRAM_ALLOWED_CHAT_IDS=1355362825 configurado; BOT_TOKEN presente |

---

### F6 — Cron + Subagentes

| Campo | Valor |
|-------|-------|
| **Missão** | Criar job cron via `POST /v1/cron/jobs` com `run_in: 60s`, aguardar execução, verificar `last_status` |
| **Critério positivo** | Linha em `cron_jobs` com `last_run != NULL` e `last_status = success`; arquivo `/tmp/d5_cron.txt` criado (se usar write_file tool) |
| **Critério negativo** | Nenhum job em `status=failed` após execução; sem loop infinito de erros no core log |
| **Evidência** | `SELECT id, name, last_run, last_status FROM cron_jobs LIMIT 5` |
| **Tempo limite** | 120 segundos |
| **Modelo** | `anthropic:claude-haiku-4-5` |
| **Observação** | Subagent isolado por construção (memory_store=None, fresh conversation_id) |

---

### F7 — Missões Persistentes + Crítico Autônomo

| Campo | Valor |
|-------|-------|
| **Missão** | Criar missão via `POST /v1/missions` com objetivo que envolva operação irreversível (ex: "delete um arquivo temporário"), aguardar steps e verificar se Critic foi consultado |
| **Critério positivo** | Linha em `critic_evaluations` com `mission_id != NULL`; step com `tools_used` contendo pelo menos 1 tool real; `mission_steps` mostra routing source != `none` |
| **Critério negativo** | Nenhum step marcado como `done` com result = prosa pura (validação de F.B ativa); Critic não bloqueia sem motivo |
| **Evidência** | `SELECT ce.mission_id, ce.verdict FROM critic_evaluations ce WHERE ce.mission_id IS NOT NULL LIMIT 5` |
| **Tempo limite** | 180 segundos |
| **Modelo** | `anthropic:claude-haiku-4-5` |
| **Observação** | Fix Fase B: executor deve rejeitar prosa como `done`. Fix D.1: routing por step ativo. |

---

### F8 — Sandboxes (exec_tool)

| Campo | Valor |
|-------|-------|
| **Missão** | Criar missão com objetivo "calcule 2+2 usando Python" — deve acionar exec_tool → SubprocessSandbox |
| **Critério positivo** | Linha em `sandbox_executions` com `profile != DEFAULT` (ou qualquer profile); step result contém output real do código executado |
| **Critério negativo** | exec_tool NÃO executado fora de sandbox (sem `profile=null`); sem escape do contexto sandbox |
| **Evidência** | `SELECT profile, exit_code, stdout FROM sandbox_executions ORDER BY created_at DESC LIMIT 3` |
| **Tempo limite** | 120 segundos |
| **Modelo** | `anthropic:claude-haiku-4-5` |

---

### F9 — Skills Voyager (SkillSynthesizer + SkillRegistry)

| Campo | Valor |
|-------|-------|
| **Missão** | Chamar `POST /api/v1/skills/synthesize` diretamente (endpoint existe no server.py local), ou criar missão que acione o loop de síntese de skills |
| **Approach direto** | Verificar se `GET /api/v1/skills` responde (router foi registrado no lifespan de F9), então chamar `/synthesize` |
| **Critério positivo** | `GET /api/v1/skills` retorna 200 (router F9 ativo); `POST /api/v1/skills/synthesize` retorna resultado (mesmo que 0 skills sintetizadas por falta de cluster) |
| **Critério negativo** | Rota não retorna 404 (router deve estar registrado); sem traceback não-tratado |
| **Evidência** | `SELECT COUNT(*) FROM skills` + resposta HTTP do endpoint |
| **Tempo limite** | 60 segundos |
| **Modelo** | N/A — teste de rota, sem necessidade de LLM |
| **Observação** | Skills router está registrado dentro de try/except no lifespan — pode ter falhado silenciosamente |

---

### F10 — Deploy VPS (Supervisor + Workers)

| Campo | Valor |
|-------|-------|
| **Missão** | Verificar health endpoints (`/live`, `/ready`, `/deep`) que foram adicionados pela F10 |
| **Critério positivo** | `/health` retorna 200 com `ok=true`; `deploy_events` tem pelo menos 1 linha de startup |
| **Critério negativo** | Nenhum container em restart loop; worker_health não tem entradas fantasma |
| **Evidência** | `SELECT * FROM deploy_events ORDER BY created_at DESC LIMIT 3`; `curl /health` + `curl /live` + `curl /ready` |
| **Tempo limite** | 30 segundos |
| **Modelo** | N/A — verificação de endpoints |
| **Observação** | Container usa Supervisor only em VPS bare-metal; em Docker, uvicorn é o processo principal. Critério ajustado para o que é verificável em Docker. |

---

### F11 — Web UI (8 painéis, WebSocket)

| Campo | Valor |
|-------|-------|
| **Pré-requisito** | Rebuild da imagem Docker (`docker compose build --no-cache core`) para incluir `agent.web` |
| **Missão** | Acessar `GET /api/v1/missions` com token HMAC válido; verificar `web_sessions` no DB |
| **Critério positivo** | `GET /api/v1/missions` retorna 200 com lista (mesmo vazia); linha em `web_sessions` após acesso autenticado |
| **Critério negativo** | Nenhum 404 na rota `/api/v1/missions`; sem erro de importação do `agent.web` no log |
| **Evidência** | `SELECT * FROM web_sessions ORDER BY created_at DESC LIMIT 3`; HTTP 200 na rota |
| **Tempo limite** | 90 segundos (incluindo rebuild) |
| **Modelo** | N/A — verificação de endpoint |
| **Observação** | Imagem atual NÃO tem agent.web. Rebuild necessário. Se rebuild falhar por timeout, marcar como NOT_APPLICABLE_INFRA. |

---

### F12 — Canais Extras (Discord, Slack, Email)

| Campo | Valor |
|-------|-------|
| **Missão** | Verificar se os canais foram inicializados na bootstrap (`bootstrap_channels`) — sem enviar mensagem real para evitar spam |
| **Approach** | Verificar `channel_messages` após bot startup; verificar se Discord/Slack bot conectou via logs do core |
| **Critério positivo** | `GET /health` mostra canais ativos (se existir campo); log do core mostra `channel.telegram.started` ou `channel.discord.started`; OU `channel_messages` tem ao menos 1 linha de keepalive/ping |
| **Critério negativo** | Nenhum erro de auth em loops; channel_messages não tem entradas duplicadas infinitas |
| **Evidência** | `SELECT channel, direction, COUNT(*) FROM channel_messages GROUP BY 1,2`; grep nos logs por `channel.*started` |
| **Tempo limite** | 60 segundos |
| **Modelo** | N/A |
| **Observação** | DISCORD_BOT_TOKEN e SLACK_BOT_TOKEN presentes no .env. Telegram bot ativo (gateway recebendo pings de 149.154.x.x). |

---

### F13 — Fine-tuning LoRA

| Campo | Valor |
|-------|-------|
| **Status** | **NOT_APPLICABLE** |
| **Motivo** | Nenhum checkpoint LoRA gerado em `core/checkpoints/`. `finetune_runs=0` no DB de produção. `benchmark_results=0`. O LoraTrainer nunca foi executado em produção. |
| **O que falta** | GPU com CUDA ou Apple Silicon com MPS; dataset de fine-tuning gerado; ciclo completo de `agent finetune` rodando sem erro |
| **Critério que seria necessário** | `finetune_runs` com `status=completed`; arquivo `.safetensors` em `core/checkpoints/`; `model_invocations` com `provider=local-lora` |

---

## Ordem de execução

1. F5 → F9 → F10 → F12 (não precisam de missão LLM — testes de API/infra diretos, rápidos)
2. F6 (cron com LLM mínimo)
3. F7 (missão com Critic — mais complexo)
4. F8 (exec_tool via missão)
5. F11 (rebuild + teste web)

## Limites e salvaguardas

- Máximo 200 chamadas Anthropic na sessão
- Máximo 1 fase por vez (sem paralelismo — evita contaminação de DB)
- Timeout por fase conforme tabela acima
- `agent_d5_validation` only — nenhum write em `agent` (produção)
- Se rebuild de imagem falhar ou demorar >5min, F11 → NOT_APPLICABLE_INFRA
