# PLAN.md — Fase 2: Roadmap de Execução
Data: 2026-06-05  
Baseado em: AUDIT_REPORT.md (2026-06-02)

---

## Princípio Norteador

> **"Não há fase done sem prova runtime real"**
>
> Critério de merge obrigatório para toda sub-fase:
> - (a) Testes unitários/integração passando
> - (b) Execução local com linha gravada na tabela correspondente no banco
> - (c) Log da execução salvo como evidência (`tests/runtime/evidence/`)

---

## Tabela de Sub-Fases

| ID | Descrição | Branch | Depende de | Esforço | Tabela de evidência | Mergeable quando |
|----|-----------|--------|-----------|---------|--------------------|--------------------|
| **A.1** | Merge `feature/d4-critic-and-d1-in-missions` (fix db_pool em subagentes) | `merge/d4-critic-missions` | — | **S** | `subagent_runs`, `critic_evaluations` | Suíte completa passa |
| **A.2** | Merge `validate/d5-runtime-revalidation` (fix skills_dir + docs D.5) | `merge/d5-validation` | — | **S** | `skills` (skills_dir path) | Suíte completa passa |
| **A.3** | Wire Critic no mission flow em `core.py` (KI-1) | `feature/critic-mission-wire` | A.1 | **M** | `critic_evaluations.mission_id != NULL` | Teste runtime C.3 pré-requisito passa |
| **A.4** | Investigar migration 001 ausente; criar se necessário | `fix/migration-001` | — | **S** | `alembic_version` em banco limpo | Banco novo sobe sem erro |
| **B.1** | Novo transport `OllamaCloudTransport` (endpoint https://ollama.com/api) | `feature/ollama-cloud-transport` | — | **M** | `model_invocations.provider = 'ollama_cloud'` | 3 testes transport passando |
| **B.2** | Tornar `ollama_cloud` o default no ModelRouter + mapeamento de tiers | `feature/ollama-cloud-default` | B.1 | **S** | `model_invocations.provider = 'ollama_cloud'` em chamada real | Chat local usa ollama_cloud |
| **B.3** | Deshardecodar modelos em TierClassifier, Critic, Planner, Reflector | `feature/unhardcode-models` | B.1, B.2 | **M** | — | Suíte passa com `ANTHROPIC_API_KEY=fake` |
| **B.4** | Atualizar `.env.example`, `config/config.yaml`, docs | `feature/ollama-cloud-default` (mesmo branch) | B.2, B.3 | **S** | — | Revisão manual |
| **C.1** | Runtime validation F5: gateway + Telegram + `pending_approvals` | `feature/rt-validate-f5` | — | **M** | `pending_approvals` ≥ 1 linha | SELECT retorna ≥ 1 |
| **C.2** | Runtime validation F6: cron + subagentes | `feature/rt-validate-f6` | — | **M** | `cron_jobs` + `subagent_runs` ≥ 1 | SELECT retorna ≥ 1 |
| **C.3** | Runtime validation F7: missão + critic | `feature/rt-validate-f7` | A.1, A.3 | **M** | `missions`, `mission_steps`, `critic_evaluations` com `mission_id` | SELECTs retornam ≥ 1 |
| **C.4** | Runtime validation F8: sandbox exec_tool | `feature/rt-validate-f8` | — | **S** | `sandbox_executions` ≥ 1 | SELECT retorna ≥ 1 |
| **C.5** | Runtime validation F9: skill auto-gerada (Voyager) | `feature/rt-validate-f9` | A.2 | **L** | `skills` + `skill_executions` ≥ 1 | Skills table populada |
| **C.6** | Runtime validation F11: Web UI session + SSE + REPL eve CLI | `feature/rt-validate-f11` | — | **M** | `web_sessions` ≥ 1 | POST /api/ui/chat retorna 200 + linha no banco |
| **D.1** | Auditoria gap de install VPS → gerar `DEPLOY_GAP.md` | `docs/deploy-gap` | — | **S** | — | `DEPLOY_GAP.md` com gaps documentados |
| **D.2** | Script `scripts/install_vps.sh` bare-metal idempotente | `feature/install-vps-script` | D.1 | **L** | — | Script rodável sem erro (dry-run local) |

---

## Sequência de Execução e Grafo de Dependências

```
Onda 1 (paralelas — sem dependências entre si):
  A.1 ──────────────────────────────────┐
  A.2 ──────────────────────┐           │
  A.4 (independente)        │           │
  B.1 ──────────────────────┼───────────┼─┐
  C.1 (independente)        │           │ │
  C.2 (independente)        │           │ │
  C.4 (independente)        │           │ │
  D.1 (independente)        │           │ │
                            ↓           ↓ ↓
Onda 2 (após dependências):
  A.3 ──── requer A.1 ──────────────────┘ │
  B.2 ──── requer B.1 ─────────────────── ┘
  C.5 ──── requer A.2
  D.2 ──── requer D.1

Onda 3:
  B.3 ──── requer B.1 + B.2
  C.3 ──── requer A.1 + A.3
  C.6 ──── independente (pode ir na Onda 1)

Onda 4:
  B.4 ──── requer B.2 + B.3 (doc update, vai junto com B.2 branch)
```

**Ordem proposta de execução (otimizando para valor/risco):**

```
Sprint 1:  A.1 → A.2 → A.4 (em paralelo)
Sprint 2:  A.3 (requer A.1)   |   B.1 (em paralelo)
Sprint 3:  B.2 + B.3 + B.4 (em sequência no mesmo branch)
Sprint 4:  C.4 → C.1 → C.2 → C.6 (mais simples primeiro)
Sprint 5:  C.3 (requer A.1 + A.3)   |   C.5 (requer A.2, mais complexo)
Sprint 6:  D.1 → D.2
```

---

## Detalhamento por Sub-fase

### A.1 — Merge d4-critic-missions
**Branch:** `merge/d4-critic-missions`  
**O que faz:** `git merge --no-ff` de `feature/d4-critic-and-d1-in-missions` em `main`, preservando lineage original e facilitando revert futuro.  
**Procedimento:**

    git checkout -b merge/d4-critic-missions main
    git merge --no-ff origin/feature/d4-critic-and-d1-in-missions \
      -m "merge: d4-critic — fix db_pool propagation em subagentes"

Se houver conflito não-trivial: **PARE e mostre ao usuário antes de continuar.** Cherry-pick só como último recurso, com aprovação explícita.  
**Commits que entram:** `522037b8`, `0099a55d`, `d59db1e0`, `9553f18a`, `424954ff`  
**Testes obrigatórios:** Suíte completa sem novas quebras. Teste de integração `test_subagent_db_pool_propagation` deve passar.  
**Evidência de merge:** `git log --oneline` mostrando merge commit + os 5 commits acima.

---

### A.2 — Merge d5-validation
**Branch:** `merge/d5-validation`  
**O que faz:** `git merge --no-ff` de `validate/d5-runtime-revalidation` em `main`, preservando lineage.  
**Procedimento:**

    git checkout -b merge/d5-validation main
    git merge --no-ff origin/validate/d5-runtime-revalidation \
      -m "merge: d5-validation — skills_dir fix + D.5 runtime re-validation docs"

Se houver conflito não-trivial: **PARE e mostre ao usuário antes de continuar.**  
**Commits que entram:** `73350f98`, `6be9c133`, `c4820c1a`, `6d9fd37e`  
**Testes obrigatórios:** Suíte completa sem novas quebras. Fix skills_dir validado via `test_skill_dir_configurable`.  
**Evidência de merge:** Skills loader não quebra quando `settings.skills_dir` aponta para diretório sem permissão de escrita.

---

### A.3 — Wire Critic no mission flow (KI-1)
**Branch:** `feature/critic-mission-wire`  
**O que faz:** Em `core/src/agent/core.py` (ponto de intercepção documentado na linha ~303), adicionar chamada ao `Critic` antes de executar qualquer ação com `SkillManifest.irreversible = True`. Resultado do Critic grava em `critic_evaluations` com `mission_id` e `task_id` preenchidos.  
**Arquivos a editar:**
- `core/src/agent/core.py` — ponto de intercepção em `_execute_tools()`
- `core/src/agent/critic/critic.py` — garantir que `mission_id` e `task_id` são aceitos como params
**Testes obrigatórios:**
- `tests/critic/test_mission_wire.py` — happy path: missão → step irreversível → `critic_evaluations.mission_id IS NOT NULL`
- `tests/critic/test_mission_wire.py` — erro: Critic retorna BLOCKED → step não executado
- `tests/critic/test_mission_wire.py` — borda: skill sem `irreversible` flag → Critic não invocado  
**Evidência de runtime:** `SELECT mission_id, task_id FROM critic_evaluations WHERE mission_id IS NOT NULL` retorna ≥ 1 linha após smoke test.

---

### A.4 — Migration 001 ausente
**Branch:** `fix/migration-001`  
**O que investiga:** Schema começa em `002_memory_schema.sql`. Verificar se `alembic_version` aceita um banco começando em 002, ou se há gap que quebre `agent db migrate` em banco virgem.  
**Se gap real:** Criar `core/migrations/001_initial.sql` com `CREATE TABLE IF NOT EXISTS` para `conversations` e `messages` (mesmas definições da 002 se elas estavam em 001 antes). Usar `IF NOT EXISTS` para idempotência.  
**Se sem gap:** Apenas adicionar comentário explicativo em `migrations/README.md`.  
**Testes:** `tests/deploy/test_migration_fresh_db.py` — banco vazio + `agent db migrate` → schema completo sem erro.

---

### B.1 — OllamaCloudTransport
**Branch:** `feature/ollama-cloud-transport`  
**O que faz:** Novo provider `ollama_cloud` separado do `ollama` (local). Usa endpoint `https://ollama.com/api`, autenticação via `OLLAMA_API_KEY` (Bearer). API compatível com OpenAI chat completions.  
**Arquivos a criar/editar:**
- `core/src/agent/models/transports/ollama_cloud.py` — novo `OllamaCloudTransport(BaseTransport)`
- `core/src/agent/models/router.py` — registrar `ollama_cloud` como provider
- `core/src/agent/config.py` — `OllamaCloudSettings` com `base_url`, `api_key`, modelos por tier
- `.env.example` — `OLLAMA_CLOUD_API_KEY`, `OLLAMA_CLOUD_BASE_URL=https://ollama.com/api`  
**Testes obrigatórios** (httpx mock, sem chamada real):
- Happy path: request formatado corretamente, resposta parseada
- Erro 401: levanta `AuthError` (não dispara fallback)
- Erro 503: levanta `InfraError` (dispara fallback)
- `OLLAMA_CLOUD_API_KEY` ausente: falha na inicialização do transport

---

### B.2 — ollama_cloud como default + mapeamento de tiers
**Branch:** `feature/ollama-cloud-default` (junto com B.3 e B.4)  
**O que faz:**
- `DEFAULT_MODEL` muda de `anthropic:claude-sonnet-4-7` para `ollama_cloud:deepseek-v3.1:cloud`
- Mapeamento de tiers no TierClassifier:

| Tier | Modelo |
|------|--------|
| INSTANT | `ollama_cloud:gpt-oss:20b-cloud` |
| FAST | `ollama_cloud:gpt-oss:120b-cloud` |
| STRATEGIC | `ollama_cloud:kimi-k2.5:cloud` |
| EPIC | `ollama_cloud:deepseek-v3.1:cloud` |

- Anthropic/OpenAI/OpenRouter continuam registrados mas não são o default
- CLI `agent model set-default <provider:model>` continua funcionando (sem mudança na lógica)

---

### B.3 — Deshardecodar modelos nos componentes
**Branch:** `feature/ollama-cloud-default` (mesmo branch)  
**Componentes afetados** (todos hardcoded em `anthropic:*` no audit):

| Componente | Arquivo | Campo atual | Novo comportamento |
|-----------|---------|------------|-------------------|
| TierClassifier | `orchestrator/tiers.py` | `anthropic:claude-haiku-4-5` | Ler de `OrchestratorSettings.classifier_model` |
| Critic médio | `critic/critic.py` | `anthropic:claude-haiku-4-5` | Ler de `CriticSettings.medium_model` |
| Critic sintetizador | `critic/critic.py` | `anthropic:claude-sonnet-4-6` | Ler de `CriticSettings.primary_model` |
| MissionPlanner | `missions/planner.py` | `anthropic:claude-haiku-4-5` | Ler de `MissionsSettings.planner_model` |
| MissionReflector | `missions/reflector.py` | `anthropic:claude-sonnet-4-6` | Ler de `MissionsSettings.reflector_model` |
| Curator | `memory/curator.py` | env `MEMORY_CURATOR_MODEL` | Manter (já usa env) |

**Valores default dos Settings** (aplicados em `config.py` quando env não definida):

| Setting | Novo default |
|---------|-------------|
| `OrchestratorSettings.classifier_model` | `ollama_cloud:gpt-oss:20b-cloud` |
| `CriticSettings.medium_model` | `ollama_cloud:gpt-oss:20b-cloud` |
| `CriticSettings.primary_model` | `ollama_cloud:kimi-k2.5:cloud` |
| `MissionsSettings.planner_model` | `ollama_cloud:gpt-oss:20b-cloud` |
| `MissionsSettings.reflector_model` | `ollama_cloud:kimi-k2.5:cloud` |

**Testes:** Rodar suíte inteira com `ANTHROPIC_API_KEY=invalid OLLAMA_CLOUD_API_KEY=test`. Nenhum componente deve tentar chamar Anthropic se `anthropic` não for o default.

---

### Pré-requisito obrigatório da Sub-fase C — Disponibilidade de Docker

**VERIFICAR ANTES DE INICIAR QUALQUER C.x:**

    docker ps

Se `docker ps` falhar ou retornar erro: **PARE imediatamente e avise o usuário.** A sub-fase C inteira depende de testcontainers ou `docker compose up -d postgres redis` para subir PostgreSQL e Redis reais. Sem Docker local disponível, nenhuma C.x pode prosseguir — não há fallback para banco em memória nesta sub-fase, pois o objetivo é validar persistência real.

---

### C.1 — Runtime validation F5 (Gateway + pending_approvals)
**Branch:** `feature/rt-validate-f5`  
**Arquivo:** `tests/runtime/test_phase_f5_real.py`  
**Setup:** testcontainers (PostgreSQL + Redis) ou `docker compose up -d postgres redis`  
**Fluxo testado:**
1. Sobe AIAgent + ApprovalManager
2. Fake message que aciona uma skill com `requires_approval=True`
3. SELECT: `SELECT COUNT(*) FROM pending_approvals` → espera ≥ 1
4. POST `/v1/approvals/{id}` com `approved=True`
5. SELECT: `SELECT COUNT(*) FROM pending_approvals WHERE status='approved'` → ≥ 1
**Evidência salva em:** `tests/runtime/evidence/f5_approval_id.txt`

---

### C.2 — Runtime validation F6 (Cron + Subagentes)
**Branch:** `feature/rt-validate-f6`  
**Arquivo:** `tests/runtime/test_phase_f6_real.py`  
**Fluxo testado:**
1. Sobe scheduler com SQLAlchemyJobStore (banco real)
2. Cria cron job via `POST /v1/cron/jobs` com `run_date=now+5s`
3. Job executa → delega para subagente
4. Aguarda até 30s: `SELECT COUNT(*) FROM cron_jobs` ≥ 1 e `SELECT COUNT(*) FROM subagent_runs` ≥ 1
**Evidência salva em:** `tests/runtime/evidence/f6_cron_job_id.txt`

---

### C.3 — Runtime validation F7 (Missão + Critic)
**Branch:** `feature/rt-validate-f7`  
**Requer:** A.1 + A.3 mergeados  
**Arquivo:** `tests/runtime/test_phase_f7_real.py`  
**Fluxo testado:**
1. POST `/v1/missions` com objetivo simples mas com pelo menos 1 step irreversível
2. Aguarda execução (timeout 60s)
3. SELECTs obrigatórios:
   - `SELECT COUNT(*) FROM missions` ≥ 1
   - `SELECT COUNT(*) FROM mission_steps` ≥ 1
   - `SELECT COUNT(*) FROM critic_evaluations WHERE mission_id IS NOT NULL` ≥ 1 (valida A.3)
**Evidência salva em:** `tests/runtime/evidence/f7_mission_id.txt`

---

### C.4 — Runtime validation F8 (Sandbox)
**Branch:** `feature/rt-validate-f8`  
**Arquivo:** `tests/runtime/test_phase_f8_real.py`  
**Fluxo testado:**
1. Chama `exec_tool` diretamente com script Python simples (`print("hello")`) e policy `DEFAULT`
2. Resultado retorna stdout com "hello"
3. SELECT: `SELECT COUNT(*) FROM sandbox_executions WHERE exit_code=0` ≥ 1
**Evidência salva em:** `tests/runtime/evidence/f8_sandbox_exec_id.txt`

---

### C.5 — Runtime validation F9 (Voyager Skills)
**Branch:** `feature/rt-validate-f9`  
**Requer:** A.2 mergeado (skills_dir fix)  
**Arquivo:** `tests/runtime/test_phase_f9_real.py`  
**Fluxo testado:** (complexo — ver abaixo)
1. Simula cluster de ≥ 5 execuções similares para disparar `SkillSynthesizer`
2. `SkillSynthesizer.synthesize()` gera um `skill_candidate`
3. `SkillValidator` valida (ast.parse + smoke run)
4. `SkillPromoter` promove para `skills_active` (via Critic — requer A.3 indiretamente)
5. `SkillRunner` executa a skill promovida
6. SELECTs: `skills` ≥ 1 linha com `status='active'`, `skill_executions` ≥ 1
**Nota de esforço L:** Pode exigir mocking pesado do LLM para a síntese. Decidir na execução se usa LLM real (com `OLLAMA_CLOUD_API_KEY`) ou stub.  
**Evidência salva em:** `tests/runtime/evidence/f9_skill_slug.txt`

---

### C.6 — Runtime validation F11 (Web UI + REPL)
**Branch:** `feature/rt-validate-f11`  
**Arquivo:** `tests/runtime/test_phase_f11_real.py`  
**Fluxo testado:**
1. Sobe core + gateway via `docker compose up -d` (ou processo direto)
2. POST `http://localhost:8000/api/ui/chat` com `Authorization: Bearer <WEB_UI_TOKEN>` e payload JSON
3. Resposta HTTP 200 recebida
4. SELECT: `SELECT COUNT(*) FROM web_sessions` ≥ 1
5. Smoke do REPL via **pexpect** (opção a — TTY emulado):
   ```python
   child = pexpect.spawn("eve", timeout=30)
   child.expect(r"[$>»]|>>>")          # aguarda prompt do REPL
   child.sendline("oi")
   child.expect(r".{5,}", timeout=30)  # aguarda resposta não-vazia
   child.sendline("/quit")
   child.wait()
   assert child.exitstatus == 0
   ```
   Justificativa para opção (a): `prompt_toolkit` exige TTY real; `echo "oi" | eve` levantaria `IOError: [Errno 25] Inappropriate ioctl for device`. Flag `--non-interactive` não foi verificada no código existente — se for encontrada durante a implementação, trocar por opção (b) sem necessidade de aprovação.
**Evidência salva em:** `tests/runtime/evidence/f11_web_session_id.txt`

---

### D.1 — Auditoria gap de install VPS
**Branch:** `docs/deploy-gap`  
**Entregável:** `DEPLOY_GAP.md` na raiz  
**O que compara:**
- `deploy/digitalocean/deploy.sh` vs instalação real conhecida na VPS
- Checklist: pip install -e . executado? npm run build executado? webui/public copiado para gateway? systemd units registradas para core E gateway? alembic upgrade head rodado?
- Cada item: EXECUTADO / PULADO / DESCONHECIDO
**Não executa nada na VPS ainda — só compara scripts vs expectativa.**

---

### D.2 — Script install_vps.sh bare-metal
**Branch:** `feature/install-vps-script`  
**Requer:** D.1 aprovado  
**Arquivo:** `scripts/install_vps.sh`  
**Cobertura:**
1. Dependências apt: `postgresql-16 postgresql-16-pgvector redis-server nodejs npm nginx certbot`
2. PostgreSQL: cria usuário `agent`, banco `agent_db`, habilita pgvector
3. Python venv: `python3 -m venv /opt/eve/venv && pip install -e .`
4. Node: `npm ci` no gateway, `npm run build`, copia `webui/public` para `gateway/public`
5. Alembic: `agent db migrate` (via entrypoint registrado)
6. systemd units: `eve-core.service` + `eve-gateway.service` (ativa + enable)
7. Bind de serviços: uvicorn core em `127.0.0.1:8000`; gateway em `127.0.0.1:3000` — nunca expostos publicamente
8. ufw: APENAS portas 22 (SSH), 80 (HTTP redirect), 443 (HTTPS) — portas 3000 e 8000 permanecem fechadas externamente
9. nginx + TLS: certbot standalone; proxy reverso `https://<dominio>/ → http://127.0.0.1:3000`; rota opcional `location /api/ { proxy_pass http://127.0.0.1:8000; }` para expor core pela mesma origem
**Idempotência:** cada passo usa `CREATE IF NOT EXISTS`, `--skip-existing`, ou checagem de existência antes de instalar.  
**Teste local:** shellcheck sem erros. Se houver acesso a Vagrant/lxc, smoke test dry-run.

> ⚠️ TODO descoberto em A.4: o repo tem dois venvs no core/ (.venv incompleto, .venv312 com deps completas). install_vps.sh deve criar UM único venv (recomendado: core/.venv) e rodar pip install -r requirements.txt + pip install -e . para garantir todas as deps (prometheus_client, discord.py, slack_*, etc.). Documentar no README também que .venv312 era artefato local e não deve ser referência.

---

## Itens Descartados do Pedido Original (Fase 2 do plano inicial)

| Item | Motivo |
|------|--------|
| **REPL CLI nativo (agent chat)** | Já existe como entrypoint `eve` (`cli.chat_cmd:app`). Validado em **C.6** ao invés de reimplementado. |
| **Web UI React+Vite+Tailwind** | Web UI HTML/JS vanilla já existe (F11 com 8 painéis, WS, auth). Reescrever em React introduziria trabalho sem valor novo. Validado em **C.6**. |
| **F12 Canais extras (Discord/Slack/Email)** | Código existe, não bloqueante para as demais features. Adiado — sem data. |
| **F13 Fine-tuning LoRA** | Caro para rodar localmente (requer GPU + datasets). Adiado — sem data. |
| **F10 Deploy VPS (validação runtime)** | Validação acontece na **Fase 5** (após merge de todas as features na main). A.4/D.1/D.2 cobrem a parte de infra. |
| **Cherry-pick em A.1/A.2** | Substituído por `git merge --no-ff` (correção 1) para preservar lineage e facilitar revert futuro. Cherry-pick só como último recurso em caso de conflito não-trivial, com aprovação explícita. |

---

## Critérios de Aprovação para Fase 3

Para cada sub-fase, a aprovação de merge requer:
1. `pytest -x` passa sem novas quebras (comparado à baseline de 1.185 passing)
2. Tabela de evidência com ≥ 1 linha (para sub-fases com validação runtime)
3. `git diff --stat main` revisado e aprovado pelo usuário
4. Log de execução salvo em `tests/runtime/evidence/`

**AGUARDANDO APROVAÇÃO ITEM POR ITEM ANTES DE INICIAR FASE 3.**
