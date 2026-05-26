# EXECUTION_AUDIT — o que foi validado vs. o que é teórico

> Data: 2026-05-25  
> Motivo: smoke test revelou que o agente gera prosa em vez de executar tools; mapeamento do escopo do problema antes de qualquer fix.  
> Branch auditada: `integration/merge-f9-f10`

---

## 1. Sinais de execução real (DB counts)

Tabelas existentes no banco em 2026-05-25:

| Tabela | Count | Observação |
|---|---|---|
| `model_invocations` | **516** | LLM sendo chamado — evidência de vida |
| `memories` | **15** | F2 ativo, mas com duplicatas (mesma frase salva 3–5x) |
| `critic_evaluations` | **9** | Todos em 2026-05-10; **0 linkados a missão ou task** |
| `subagent_runs` | **5** | 4 do smoke test (TEATRO); 1 "ping" (2026-05-14) |
| `skill_invocations` | **4** | 2 `summarize_text` (sucesso); 2 `web_research` (falha) |
| `reflexive_memory` | **3** | Inserções de 2026-05-23 |
| `cron_jobs` | **2** | 1 nunca rodou; 1 rodou 1x com `last_status = failed` |
| `missions` | **2** | Única missão `done` = TEATRO (ver seção 3) |
| `mission_steps` total | **10** | 6 done / 4 failed |
| `skills` (F9 table) | **0** | Tabela existe, zero rows |
| `skill_candidates` | **0** | F9 Voyager nunca rodou |
| `skill_executions` | **0** | F9 executor nunca acionado |
| `sandbox_executions` | **0** | F8 nunca exercitado |
| `pending_approvals` | **0** | F5 nunca exercitado |
| `outbound_messages_log` | **0** | F5 nunca exercitado |
| `channel_messages` | **0** | F12 nunca exercitado |
| `finetune_runs` | **0** | F13 nunca exercitado |
| `benchmark_results` | **0** | F13 nunca exercitado |
| `web_sessions` | **0** | F11 nunca exercitado |
| `deploy_events` | **0** | F10 nunca exercitado |
| `worker_health` | **0 rows** | Tabela existe, zero workers já registrados |

**Providers de LLM confirmados em uso real:**

| Provider | Modelo | Chamadas | 100% sucesso |
|---|---|---|---|
| anthropic | claude-sonnet-4-6 | 312 | ✓ |
| anthropic | claude-haiku-4-5 | 184 | ✓ |
| ollama | gpt-oss:20b | 9 | ✓ |
| ollama | qwen3-coder:480b | 8 | ✓ |
| ollama | qwen2.5:7b | 3 | ✓ |

---

## 2. Classificação por fase

| Fase | Componente | Status declarado | Status real (DB) | Discrepância |
|---|---|---|---|---|
| **F0** | Fundação (Docker, Postgres, Redis) | ENTREGUE | **VALIDADO** — implícito pelo fato do stack rodar | Nenhuma |
| **F1** | Core mínimo (AIAgent, conversation loop) | ENTREGUE | **VALIDADO** — 516 model_invocations confirmam LLM core funcional | Nenhuma |
| **F2** | Memória (MemoryStore, Curator, ContextCompressor) | ENTREGUE | **PARCIAL** — 15 memórias salvas, mas 12/15 são a mesma frase duplicada; Curator seleciona, mas sem critério efetivo | Mínimo |
| **F3** | Skills builtin (SkillManager, SkillRunner, SkillCreator) | ENTREGUE | **PARCIAL** — 4 skill_invocations (2 `summarize_text` com sucesso, 2 `web_research` com falha); nunca criou skill nova via SkillCreator em runtime | Skills YAML rodaram; criação dinâmica TEÓRICA |
| **F4** | Multi-modelo (ModelRouter, Transports) | ENTREGUE | **VALIDADO** — 5 modelos distintos, 3 providers, 516 chamadas | Nenhuma |
| **F5** | Gateway Node + Telegram (Approvals) | ENTREGUE | **TEÓRICO** — pending_approvals=0, outbound_msgs=0 | SIM — gateway pode estar rodando, mas nunca gerou mensagem ou approval real |
| **F6** | Cron + Subagentes | ENTREGUE | **TEÓRICO** — 5 subagent_runs todos com resultado TEATRO; cron rodou 1x com status `failed` | SIM — subagentes são instanciados mas não executam tools (ver seção 4) |
| **F7** | Missões + Crítico Autônomo | ENTREGUE | **TEÓRICO** — 2 missões ambas TEATRO; 9 critic_evaluations sem link a missão/task (provavelmente de testes) | SIM — mission executor marca steps como `done` sem tool calls; critic não é acionado no flow de missões |
| **F8** | Sandboxes (SubprocessSandbox, DockerSandbox) | ENTREGUE | **TEÓRICO** — sandbox_executions=0 | SIM — exec_tool nunca acionado em runtime |
| **F9** | Skills Voyager (SkillSynthesizer, SkillRegistry) | ENTREGUE | **TEÓRICO** — skills table=0 rows, skill_candidates=0, skill_executions=0 | SIM — nenhuma skill foi sintetizada, registrada ou executada via F9 |
| **F10** | Deploy VPS (Supervisor, Workers) | ENTREGUE | **TEÓRICO** — deploy_events=0, worker_health=0 rows | SIM — supervisor nunca arrancou workers em runtime real |
| **F11** | Web UI (8 painéis, WebSocket) | ENTREGUE | **TEÓRICO** — web_sessions=0 | SIM — UI pode existir mas nunca foi acessada |
| **F12** | Canais extras (Discord, Slack, Email) | ENTREGUE | **TEÓRICO** — channel_messages=0 | SIM — adaptadores têm código, nunca receberam ou enviaram mensagem |
| **F13** | Fine-tuning LoRA | ENTREGUE | **TEÓRICO** — finetune_runs=0, benchmark_results=0 | SIM — LoraTrainer nunca foi executado |

**Legenda:**
- **VALIDADO** — evidência positiva de execução real, com efeito verificável
- **PARCIAL** — alguma execução real, mas funcionalidade central não exercitada
- **TEÓRICO** — código existe e testes passam, mas nunca rodou em runtime real

---

## 3. Missões analisadas

### Missão 1 — `smoke-loc-real` (2026-05-23) — **TEATRO**

| Step | Descrição | Status | Classificação | Evidência |
|---|---|---|---|---|
| 0 | Verificar existência e permissões do diretório `core/src/agent` | done | TEATRO | `"Vou verificar primeiro se o diretório existe listando o conteúdo..."` — intenção declarada, sem tool call |
| 1 | Listar recursivamente arquivos `.py` | done | TEATRO | `"não tenho acesso direto ao sistema de arquivos do seu ambiente local"` |
| 2 | Contar linhas de código de cada `.py` | done | TEATRO | `"Não estou conseguindo avançar com a tarefa devido à falta de acesso direto ao sistema de arquivos"` |
| 3 | Formatar resultados como `<caminho>: <linhas>` | done | TEATRO | `"Entendi. Quando você me pedir para ler arquivos, vou formatar..."` — instrução futura, sem execução |
| 4 | Escrever output em `/tmp/loc_real.txt` | done | TEATRO | `"Não tenho informações suficientes... Poderia fornecer mais detalhes?"` |

**Resultado:** 5/5 steps marcados `done`. Nenhuma tool foi chamada. Arquivo `/tmp/loc_real.txt` não existe. Missão marcada como `status=done` pelo executor mesmo sem efeito real algum.

**Detalhe revelador dos subagent_runs:** O campo `tools_used` mostra `{web_search,read_file,salvar_memoria,ler_memoria}` para todos os 4 subagentes desta missão — mas esse é o set de tools **injetadas** (disponíveis), não as que foram **executadas**. O summary de cada subagente é prosa idêntica aos steps de missão acima.

---

### Missão 2 — `Pesquisar frameworks Python` (2026-05-10) — **TEATRO/INCONCLUSIVO**

| Step | Descrição | Status | Classificação |
|---|---|---|---|
| 0 | Acessar PyPI.org e consultar downloads | done | TEATRO (result=`{"text":""}` — vazio) |
| 1 | Consultar GitHub Trending | failed | INCONCLUSIVO (sem result) |
| 2 | Pesquisar Stack Overflow Trends | failed | INCONCLUSIVO (sem result) |
| 3 | Compilar dados comparativos | failed | INCONCLUSIVO (sem result) |
| 4 | Redigir documento final | failed | INCONCLUSIVO (sem result) |

**Resultado:** Missão parada em `status=active`. Step 0 passou com result vazio; os 4 seguintes falharam sem deixar trace de tentativa.

---

## 4. Padrão de prosa em todos os steps `done`

Query A.4 executada em 2026-05-25:

| Métrica | Count | % |
|---|---|---|
| Total steps `done` | 6 | 100% |
| Pattern "não tenho acesso" | 1 | 16.7% |
| Pattern "preciso que você" | 1 | 16.7% |
| Pattern "Entendi" / chitchat | 1 | 16.7% |
| Result vazio `{"text":""}` | 1 | 16.7% |
| **Prosa (qualquer tipo)** | **5** | **83.3%** |
| Output estruturado real (JSON com tool output) | 0 | 0% |
| `looks_like_json` (inclui `{"text":"<prosa>"}`) | 6 | 100% — enganoso |

> **Nota:** `looks_like_json=6` é falso positivo. O formato é sempre `{"text": "<prosa natural>"}` — não um resultado de tool call. O executor aceita qualquer JSON como output válido, inclusive prosa embrulhada em JSON.

**Confirmação da hipótese:** O problema é **sistêmico**. Em 100% das execuções registradas, o autonomous mission executor marcou steps como `done` sem que uma tool call real tenha sido efetuada.

---

## 5. Diagnóstico complementar

### Por que `critic_evaluations=9` não valida F7?

As 9 avaliações foram criadas em 2026-05-10 (mesmo dia das skill_invocations de `web_research`). **Nenhuma tem `mission_id` ou `task_id` preenchido.** Isso indica que foram acionadas diretamente via API ou teste de integração, não pelo flow de missões. O Critic não está integrado ao executor de missões em runtime.

### Por que `subagent_runs=5` não valida F6?

O campo `tools_used` em `subagent_runs` registra as tools **disponíveis no contexto do subagente**, não as que foram chamadas. Os summaries de todos os 5 runs são prosa (teatro idêntico ao das missions). `success=true` foi gravado porque o executor não valida se houve tool call — qualquer resposta não-exception é marcada como sucesso.

### Por que `memories=15` é "parcial" e não "validado"?

A tabela tem 15 entradas, mas 12/15 são variações da mesma frase (`"O usuário prefere respostas concisas e diretas"` e `"O projeto com tag <hash> se chama OpenClaw"`). O Curator salva memórias de forma redundante sem deduplicação efetiva. A funcionalidade existe, mas o critério de qualidade está ausente.

---

## 6. Conclusão

Das 14 fases (F0–F13):

- **2 fases VALIDADAS** (F0, F1 core + F4 multi-model) — têm evidência de execução real com efeito verificável
- **2 fases PARCIAIS** (F2 memória, F3 skills builtin) — alguma execução, mas funcionalidade central incompleta ou redundante
- **10 fases TEÓRICAS** (F5, F6, F7, F8, F9, F10, F11, F12, F13 + F3 parcial com SkillCreator) — código existe, testes mockados passaram, nunca exercitado em runtime real

> **Percentual de fases com execução real verificada: ~14% (2/14)**  
> **Percentual de fases teóricas: ~71% (10/14)**

### Causa-raiz identificada

O executor do autonomous mission loop (`core/src/agent/autonomous/loop.py` e o mecanismo de steps em `core/src/agent/api/missions.py`) **não valida se o LLM executou tool calls**. Ele envia o prompt para o LLM e persiste qualquer resposta textual como `result`, marcando o step como `done` independentemente do conteúdo. O LLM sem acesso a tools reais (ou sem instrução explícita de usá-las) responde em linguagem natural — o que é registrado como "execução bem-sucedida".

---

## 7. Recomendação pra Fase B

**O problema é sistêmico, não pontual.** A maioria das fases é TEÓRICA.

**Prioridade 1 — fix do executor (bloqueador de tudo):**
Antes de qualquer nova feature, o mission step executor precisa:
1. Validar que a resposta do LLM contém ao menos uma tool call real
2. Rejeitar prosa pura como resultado de step "done"
3. Marcar como `failed` (com `error`) quando o LLM não usa tools no contexto de um step operacional

**Prioridade 2 — smoke test sequencial por fase:**
Após fix do executor, re-executar um smoke test mínimo para F5 (Telegram), F8 (Sandbox), F9 (Voyager), F11 (Web), F12 (Canais), F13 (Finetune) — nessa ordem.

**Prioridade 3 — critério de aceite revisto:**
"Testes passando" ≠ "fase entregue". O critério mínimo deve ser: ao menos 1 execução real em runtime com efeito verificável persistido no banco.

---

*Auditoria realizada por Claude Code em 2026-05-25. Queries executadas diretamente contra `agent-postgres-1`. Nenhuma alteração no banco ou no código foi feita durante esta fase.*
