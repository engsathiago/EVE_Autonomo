# Fase 6 — Cron + Subagentes

> Pré-requisito: Fases 0-5 concluídas e validadas (Gateway Node + Telegram + aprovações funcionando).
> Objetivo: tirar o agente do modo reativo. Ele passa a ter um relógio interno (cron) e a saber dividir trabalho em sub-tarefas paralelas (subagentes), executadas via Orquestrador com Execution Tiers.
>
> **Esta é a fase que transforma chatbot em agente.** Nada do que vier depois (missões persistentes, Voyager, deploy 24/7) faz sentido sem ela.

---

## 1. Objetivo

Até a Fase 5, o agente só faz alguma coisa quando **alguém manda mensagem**. Não tem loop próprio, não tem relógio, não consegue rodar duas tarefas em paralelo, e quando uma tarefa é grande ele tenta resolver tudo na mesma cadeia ReAct (estoura contexto e perde foco).

A Fase 6 introduz três componentes que mudam isso:

1. **Scheduler (cron)** — APScheduler persistido em Postgres. Permite agendar jobs por cron expression (`"0 9 * * 1"`) ou linguagem natural (`"toda segunda às 9h"`). Cada job dispara uma `Task` no agente sem precisar de input humano. Sobrevive a restart.

2. **Subagent Pool** — `delegate(task, context, tools)` cria um subagente filho com contexto isolado (system prompt enxuto, memória própria, conjunto de tools restrito). O subagente roda, devolve resultado, morre. O pai recebe um sumário, não o trace inteiro. Isso preserva contexto do pai e permite paralelismo real.

3. **Orquestrador com Execution Tiers** — antes de delegar, o orquestrador classifica a tarefa em um dos quatro tiers:

   | Tier | Quando | Como executa |
   |---|---|---|
   | `INSTANT` | Resposta direta, sem tool | Pai responde inline. Sem subagente. |
   | `FAST` | 1 tool, escopo pequeno | Pai executa direto. Sem delegar. |
   | `STRATEGIC` | Múltiplos passos, escopo médio | 1 subagente sequencial. |
   | `EPIC` | Vários componentes independentes | N subagentes em paralelo + agregador final. |

   Inspirado no padrão do `gaahzx/jarvis`, mas operacional (nada de vocabulário pomposo — só regra de roteamento).

No fim da fase: você consegue rodar `agent cron add "todo dia às 8h" --task "buscar notícias de IA e me mandar resumo no Telegram"`, fechar o terminal, e às 8h da manhã o agente acorda sozinho, divide o trabalho em buscar+filtrar+resumir+enviar (cada um em subagente), e a mensagem chega no seu Telegram.

---

## 2. Arquitetura

### 2.1 Componentes novos

```
core/
├── scheduler/
│   ├── __init__.py
│   ├── store.py             # CRUD de jobs em Postgres
│   ├── parser.py            # NL → cron expression (via LLM)
│   ├── worker.py            # APScheduler async, persistido
│   └── triggers.py          # cron, interval, oneshot
│
├── orchestrator/
│   ├── __init__.py
│   ├── tiers.py             # Enum + heurística de classificação
│   ├── router.py            # decide tier e como executar
│   └── aggregator.py        # junta resultados de subagentes EPIC
│
├── subagents/
│   ├── __init__.py
│   ├── pool.py              # cria/destrói subagentes
│   ├── subagent.py          # AIAgent filho com contexto isolado
│   ├── context.py           # SubAgentContext (tools subset, system msg)
│   └── delegate_tool.py     # Tool `delegate` que o pai usa
│
├── tasks/
│   ├── __init__.py
│   ├── store.py             # tabela de tasks (status, resultado, parent)
│   └── task.py              # dataclass Task
│
└── tests/
    ├── scheduler/
    ├── orchestrator/
    └── subagents/
```

### 2.2 Fluxo de uma mensagem com Orquestrador

```
1. Mensagem chega (Telegram, CLI, ou cron)
2. Core cria Task(id, source, content, parent=None)
3. Orchestrator.route(task):
   a. Chama LLM rápida (Haiku/Qwen 7B) com prompt de classificação
   b. Decide tier: INSTANT | FAST | STRATEGIC | EPIC
4. Executa conforme tier:
   - INSTANT → AIAgent.respond_inline(task) → fim
   - FAST → AIAgent.run(task, max_iterations=3) → fim
   - STRATEGIC → SubagentPool.spawn(task, tools_subset) → 1 filho
   - EPIC → planner divide em N subtasks → SubagentPool.spawn_parallel(subtasks)
            → Aggregator.merge(results) → resposta final
5. Resposta volta pro source original (Telegram, CLI, etc)
6. Task marcada done, resultado persistido
```

### 2.3 Fluxo de um job cron

```
1. Worker APScheduler dispara no horário
2. Carrega CronJob do banco (id, cron_expr, task_template, source)
3. Cria Task(source="cron", content=task_template, cron_job_id=X)
4. Empurra pra Orchestrator.route() — daí em diante é igual a uma mensagem normal
5. Resultado é entregue no canal configurado (default: Telegram do owner)
6. Atualiza last_run, next_run no banco
```

### 2.4 Fluxo de um subagente

```
Pai chama tool: delegate(
    task="buscar últimas 5 notícias de IA em pt-BR",
    tools=["web_search", "memory_read"],
    timeout=120,
    return_format="json_list"
)

→ SubagentPool.spawn():
  - Cria SubAgentContext: system prompt enxuto + tools subset + memória ISOLADA da sessão
  - Instancia AIAgent filho com esse contexto
  - Roda loop ReAct até task.done ou timeout
  - Retorna resultado serializado (não trace completo)
  - Mata o subagente

Pai recebe: { "ok": true, "result": [...], "iterations": 4, "tokens_used": 1820 }
```

Crítico: **subagente não vê contexto do pai além do que o pai passa em `task` e `extra_context`**. Isso é o que protege o pai de context rot.

---

## 3. Schema novo

### 3.1 `cron_jobs`

```sql
CREATE TABLE cron_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    cron_expr   TEXT NOT NULL,              -- ex: "0 9 * * 1"
    nl_original TEXT,                        -- "toda segunda às 9h"
    task_tpl    TEXT NOT NULL,               -- prompt que vira Task
    source      TEXT NOT NULL,               -- canal de saída (telegram, cli, ...)
    target      TEXT,                        -- chat_id, user_id, etc
    enabled     BOOLEAN DEFAULT TRUE,
    last_run    TIMESTAMPTZ,
    next_run    TIMESTAMPTZ,
    last_status TEXT,                        -- ok | failed | skipped
    last_error  TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cron_jobs_enabled_next ON cron_jobs(enabled, next_run);
```

### 3.2 `tasks`

```sql
CREATE TABLE tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
    cron_job_id   UUID REFERENCES cron_jobs(id) ON DELETE SET NULL,
    source        TEXT NOT NULL,            -- telegram | cli | cron | subagent
    content       TEXT NOT NULL,
    tier          TEXT,                     -- INSTANT | FAST | STRATEGIC | EPIC
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed | timeout
    result        JSONB,
    error         TEXT,
    iterations    INT DEFAULT 0,
    tokens_in     INT DEFAULT 0,
    tokens_out    INT DEFAULT 0,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tasks_parent ON tasks(parent_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_cron_job ON tasks(cron_job_id);
```

### 3.3 `subagent_runs` (observabilidade dos filhos)

```sql
CREATE TABLE subagent_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id      UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    parent_task  UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tools_used   TEXT[],
    duration_ms  INT,
    success      BOOLEAN,
    summary      TEXT,                       -- resumo curto pro pai
    raw_trace    JSONB,                      -- trace completo (debug)
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. Interface (CLI + tools internas)

### 4.1 Comandos novos no CLI

```bash
# CRON
agent cron add "todo dia às 8h" --task "resumo de notícias de IA" --source telegram
agent cron list
agent cron show <id>
agent cron disable <id>
agent cron enable <id>
agent cron remove <id>
agent cron run-now <id>          # dispara fora do horário (debug)

# TASKS
agent task list --status running
agent task show <id>
agent task tree <id>             # mostra árvore pai → filhos
agent task cancel <id>

# ORCHESTRATOR
agent orchestrator stats         # contadores por tier nas últimas 24h
```

### 4.2 Tool nova `delegate`

Skill (no formato Fase 3) registrada como builtin:

```markdown
---
name: delegate
description: Delegar uma sub-tarefa a um subagente isolado, útil para escopo restrito ou execução paralela
tools_allowed: [web_search, filesystem_read, memory_read, summarize_text]
input_schema:
  task: str
  tools: list[str]
  timeout: int = 120
  return_format: "text" | "json" | "json_list" = "text"
---

Você é um subagente focado. Resolva exatamente a `task` recebida usando apenas
as tools listadas. Não invente escopo. Quando terminar, devolva o resultado
no formato pedido em `return_format` e PARE.
```

O pai chama `delegate(task=..., tools=..., return_format=...)` como qualquer outra tool. O Orchestrator interpreta e cria o subagente.

### 4.3 Configuração

`config.yaml` ganha:

```yaml
orchestrator:
  classifier_model: "haiku"        # modelo rápido pra classificar tier
  classifier_max_tokens: 200
  fast_max_iterations: 3
  strategic_max_iterations: 8
  epic_max_parallel: 4
  epic_max_iterations_per_child: 6

scheduler:
  enabled: true
  timezone: "America/Sao_Paulo"
  misfire_grace_seconds: 60        # tolerância se servidor estava offline
  max_instances: 3                 # mesmo job rodando em paralelo

subagents:
  default_timeout_seconds: 120
  hard_timeout_seconds: 300
  max_concurrent_global: 8
```

---

## 5. Heurística do classificador de tiers

O `Orchestrator.route()` chama uma LLM rápida com este prompt (literal, em inglês curto pra reduzir tokens):

```
Classify the user task into ONE tier:
- INSTANT: pure conversation, definition, opinion. No tool needed.
- FAST: needs 1 tool call. Single fact lookup, single file read.
- STRATEGIC: 2-5 steps, single domain (e.g. research one topic).
- EPIC: independent parallel work (e.g. monitor 3 sites + summarize each).

Reply with ONE word: INSTANT, FAST, STRATEGIC, or EPIC.

Task: <task.content>
```

Se a LLM responder algo fora do enum → fallback `STRATEGIC` (mais seguro que `EPIC`, evita explosão de subagentes em caso de erro de parsing).

Tem uma override manual: skill ou tool podem declarar `force_tier: STRATEGIC` no manifest, e o Orchestrator respeita.

---

## 6. Persistência do APScheduler

Crítico: scheduler precisa **sobreviver a restart**. Configuração:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

scheduler = AsyncIOScheduler(
    jobstores={
        "default": SQLAlchemyJobStore(url=settings.DATABASE_URL),
    },
    timezone=settings.SCHEDULER_TZ,
    job_defaults={
        "coalesce": True,                    # se perdeu vários, roda 1 vez
        "max_instances": settings.MAX_INSTANCES,
        "misfire_grace_time": settings.MISFIRE_GRACE,
    },
)
```

Não usa Redis pra persistência (Redis é volátil aqui — vai pra Postgres).
Tabela `apscheduler_jobs` é gerenciada pelo próprio APScheduler — convive com `cron_jobs` (que é nosso domínio).

Relação: cada `cron_jobs.id` tem 1 entrada em `apscheduler_jobs`. Quando você faz `agent cron disable`, removemos do APScheduler mas mantemos em `cron_jobs` com `enabled=false`.

---

## 7. Parser NL → Cron

```python
# scheduler/parser.py
async def parse_natural(expression: str, llm: LLMClient) -> str:
    """
    "toda segunda às 9h" → "0 9 * * 1"
    "a cada 30 minutos"  → "*/30 * * * *"
    "todo dia 1 do mês"  → "0 0 1 * *"
    """
    prompt = PARSER_PROMPT.format(expr=expression)
    raw = await llm.complete(prompt, max_tokens=50, temperature=0)
    cron_expr = extract_cron(raw)
    validate_cron(cron_expr)   # croniter
    return cron_expr
```

Validação dupla:
1. `croniter.is_valid(expr)` — sintática
2. Computar `next_run` 3 vezes seguidas e checar se as datas são razoáveis (ex: não pode dar 1970 ou ano 9999) — semântica.

Se falhar → erro pro usuário com a expressão original e a inválida que a LLM tentou.

---

## 8. Observabilidade

Tudo passa pelo logger estruturado da Fase 0 (`agent.observability.logger`).
Eventos novos:

```python
log.event("orchestrator.classified", task_id=..., tier=..., latency_ms=...)
log.event("subagent.spawned", parent_id=..., child_id=..., tools=...)
log.event("subagent.finished", child_id=..., success=..., iterations=..., tokens=...)
log.event("cron.triggered", job_id=..., next_run=...)
log.event("cron.completed", job_id=..., status=..., duration_ms=...)
```

Métricas (em memória, expostas via `agent orchestrator stats`):
- contador por tier nas últimas 24h
- p50/p95 de latência por tier
- taxa de sucesso de subagentes
- subagentes ativos agora

---

## 9. Aprovação humana (integração com Fase 5)

**Crítico**: cron + subagentes não pode virar canhão sem freio. Regras:

1. Toda tool com `requires_confirmation: true` continua passando pelo fluxo de aprovação Telegram da Fase 5.
2. Se um subagente quer chamar tool sensível, o pedido sobe **pro pai**, e o pai (que tem o `source` original) sobe pra aprovação humana. Subagente espera.
3. Cron job tem flag `auto_confirm_tier: INSTANT|FAST|all|none` (default `FAST`). Se nível tier de risco for maior, escala. Default conservador.
4. Tarefa EPIC com mais de N subagentes (default 4) **sempre** pede confirmação no primeiro disparo. Depois disso, lembra a aprovação por X horas (idempotência por hash da task).

---

## 10. Testes

### Unit
- `tests/scheduler/test_parser.py` — 20 frases de teste (BR pt) → cron expressions corretas.
- `tests/scheduler/test_store.py` — CRUD básico.
- `tests/orchestrator/test_tiers.py` — mocka classifier, valida roteamento por tier.
- `tests/subagents/test_pool.py` — spawn, timeout, cancelamento.
- `tests/subagents/test_context.py` — subagente NÃO recebe memória do pai por default.

### Integração (com Postgres + Ollama mock)
- `test_cron_persistence.py`: cria job, derruba app, sobe de novo → job ainda lá, `next_run` correto.
- `test_epic_parallelism.py`: tarefa EPIC com 3 subtasks → cria 3 subagentes em paralelo, agrega.
- `test_subagent_isolation.py`: subagente não vê dados do pai além do `task` e `extra_context`.
- `test_approval_propagation.py`: subagente pede tool sensível → pedido chega no Telegram (mockado).

### End-to-end manual
- Criar cron job "a cada 5 minutos: me mande 'oi' no Telegram" → esperar 10 min → ver 2 mensagens chegando.
- Tarefa EPIC manual via CLI: "monitore esses 3 sites e me dê resumo de cada" → ver no log 3 subagentes criados em paralelo.

---

## 11. Riscos & decisões

| Risco | Mitigação |
|---|---|
| Subagente entra em loop infinito | `hard_timeout_seconds=300`. Pool mata na unha. |
| Cron dispara enquanto outro do mesmo job ainda roda | `max_instances` no APScheduler. Default 3. |
| Servidor offline → backlog enorme de cron | `coalesce=true` + `misfire_grace_time=60s`. Perdeu, perdeu. |
| Classifier erra e manda tudo pra EPIC (custo explode) | Hard cap `max_concurrent_global=8`. Acima disso, fila. |
| Subagente vaza contexto do pai por curiosidade | Contexto isolado por construção. System prompt do filho **não** tem histórico do pai. |
| Aprovações Telegram param de chegar (Fase 5 com bug) | Default `auto_confirm_tier=FAST` pra cron — não trava agente em caso de Telegram down. Mas alerta no log. |
| Custo de LLM no classifier (1 chamada por mensagem) | Modelo barato (Haiku ou Qwen 7B local). Cache por hash da task últimos 5 min. |
| Tarefa EPIC com filhos que falham silenciosamente | Aggregator marca `partial=true` se algum filho falhou. Pai vê isso e decide retry. |
| Cron job com prompt malicioso injetado (futuro) | Toda task de cron passa pelo mesmo guardrail de tool calls. Sem bypass. |

---

## 12. Critérios de aceitação

- [ ] `agent cron add "a cada 2 minutos" --task "log: ping"` cria job e ele dispara duas vezes em 4 min.
- [ ] Restart do core: `docker compose restart core` — jobs continuam disparando depois do restart, sem reagendamento manual.
- [ ] `agent cron list` mostra `next_run` correto (timezone São Paulo).
- [ ] `agent cron remove <id>` para o job no APScheduler **e** marca disabled no banco.
- [ ] Tarefa simples ("oi tudo bem") é classificada como `INSTANT` e não cria subagente. Latência < 2s.
- [ ] Tarefa "leia o arquivo X.md" é classificada `FAST`, executa direto, 1 tool call.
- [ ] Tarefa "pesquise sobre Voyager paper e me dê 3 takeaways" é `STRATEGIC`, cria 1 subagente.
- [ ] Tarefa "monitore esses 3 sites: A, B, C, e me dê resumo de cada" é `EPIC`, cria 3 subagentes em paralelo. Confere no banco que 3 rows em `subagent_runs` foram criadas no mesmo segundo (±2s).
- [ ] Subagente que demora mais que `timeout` é morto e devolve `{ok:false, error:"timeout"}` pro pai. Pai continua.
- [ ] `agent task tree <id>` mostra a árvore correta pra uma tarefa EPIC (1 pai, N filhos).
- [ ] `agent orchestrator stats` mostra contadores por tier nas últimas 24h.
- [ ] Subagente que tenta chamar tool sensível dispara aprovação Telegram (testado com tool mock).
- [ ] Todos os testes do passo 10 passando.
- [ ] `docker compose up -d` continua subindo limpo.
- [ ] CLAUDE.md atualizado com status da Fase 6 e exemplos.

---

## 13. O que NÃO é Fase 6 (deixa pra depois)

- ❌ Missões persistentes com objetivo de longo prazo (Fase 7).
- ❌ Crítico autônomo que aprova/reprova ações sem você (Fase 7).
- ❌ Conclave de 3 personas em decisões irreversíveis (Fase 7).
- ❌ MissionReflector com formato ENTREGUE/QUALIDADE/PRÓXIMO/APRENDIDO (Fase 7).
- ❌ Subagente rodando em sandbox isolado de processo/Docker (Fase 8).
- ❌ Subagente que cria skill nova depois de N usos (Fase 9 — Voyager).
- ❌ Loop noturno de reflexão/consolidação de aprendizado (Fase 9).
- ❌ Web UI mostrando árvore de tasks ao vivo (Fase 11).
- ❌ Curriculum auto-proposto.

Mantenha disciplina. Se o Claude Code propor mais que isso, recuse e aponte a fase certa.

---

## 14. Estimativa

- Sessão Claude Code: ~3-4h de execução, ~$3-5 USD.
- Você revisando + testando cron real (precisa esperar disparos): ~2h.
- Total wall-clock: 1 dia se nada quebrar. 2 dias com debug realista.

---

## 15. Anti-padrões a evitar (lições do gaahzx/jarvis e EVE-Agent TS)

- ❌ **Não copiar `bypassPermissions`** do Jarvis. Aprovação Telegram é freio fundamental.
- ❌ **Não criar dependência de Claude Code CLI** pra rodar subagentes. Subagente é AIAgent filho, não processo externo.
- ❌ **Não usar vocabulário pomposo** (AIOX, Synapse, KAIROS, atratores, autoDream). Componentes nomeados pelo que fazem: `Orchestrator`, `SubagentPool`, `CronWorker`.
- ❌ **Não auto-promover tier sem heurística clara**. Toda promoção tem prompt explícito.
- ❌ **Não deixar subagente escrever no Postgres principal**. Subagente recebe handle de leitura. Escrita só via tool registrada com permissão explícita.
