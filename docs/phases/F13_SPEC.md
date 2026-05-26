# F13 — Fine-tuning Local (LoRA) com Benchmark Gates

> Fase 13 do agente autônomo. Pré-requisito: F12 fechada na tag `phase-12-done`, com canais extras (Discord, Slack, Email) no ar e gateway multi-canal estável. O agente roda 24/7 há semanas, gerou volume de traces, F9 (Skills Voyager) tá maduro com skills auto-criadas em uso, e F10 (deploy) tá em produção.

---

## 1. Contexto

A F9 já deu ao agente a capacidade de **aprender por skills** — conhecimento externo, indexado, reutilizável. Isso é Nível 1 de aprendizado, e é onde está o ganho prático real.

A F13 entra no **Nível 2**: fine-tuning periódico do modelo local (Qwen 2.5 ou Llama 3.x, rodando em Ollama no host) com LoRA. **Não é treinar Claude** — Claude é API fechada. É treinar o modelo open-source que o agente usa pra tarefas locais (resumir, classificar, gerar drafts, decidir tier no Orchestrator quando confidence é baixa).

**Princípio inegociável da F13:** sem benchmark, não tem fine-tuning. Toda rodada de treino passa por um **eval harness** com tarefas fixas. Se o modelo treinado fica pior que o base em qualquer eixo, o checkpoint é **rejeitado automaticamente** e o agente continua com o anterior. Isso evita o caminho do eve-ts antigo (synthetic pair generation sem benchmark = drift mascarado de "evolução").

A F13 **não é autônoma por padrão**. O loop de treino é disparado por humano (`agent finetune run`) ou por cron explícito (1x por semana, configurável). O agente **não decide sozinho** treinar — porque um modelo pior em produção quebra o resto do sistema, e essa decisão precisa de gate humano nas primeiras N rodadas (configurável, default 5).

---

## 2. Princípios

- **Nada de mística.** Nomes: `TraceCollector`, `DatasetBuilder`, `LoraTrainer`, `BenchmarkRunner`, `CheckpointGate`. Sem "EvolutionEngine", "Genesis", "Awakening".
- **Benchmark é pré-requisito, não consequência.** Suite de eval com pelo menos 50 tarefas fixas + rubrica de avaliação **existe antes** da primeira rodada de treino. Sem isso, `agent finetune run` falha com erro claro.
- **Gate duro no checkpoint.** Modelo treinado só vira ativo se: (a) score médio no benchmark >= score do base + threshold (default 3%), E (b) nenhum eixo individual regrediu mais que 5%, E (c) safety_check passou (não pode gerar conteúdo violento/sexual/etc onde o base não gerava).
- **Versionamento explícito.** Cada checkpoint é um diretório `models/checkpoints/<base>-lora-<YYYYMMDD>-<hash>/` com manifest, dataset usado, scores, rubrica. Imutável.
- **Rollback é trivial.** `agent finetune activate <checkpoint_id>` muda o modelo ativo. Sempre tem caminho de volta pro base.
- **Dataset é auditável.** Cada exemplo no dataset tem origem rastreável (qual trace, qual missão, qual skill). Sem dataset gerado por LLM-juiz sem revisão humana nos primeiros ciclos.
- **Treino é local.** Roda na GPU da máquina do Thiago (RTX 4070 Ti Super ou similar). Sem dependência de cloud. Sem subida de dados.
- **Catastrophic forgetting é monitorado.** Benchmark tem categoria "base capabilities" (matemática básica, raciocínio, instrução simples) que o modelo treinado **não pode** regredir. Se regredir → reject.
- **Anti-pomposidade.** Toda métrica é numérica e definida. "Melhor" não existe — só "X% acima/abaixo do baseline no eixo Y".

---

## 3. Arquitetura

### 3.1 Módulos novos

```
agent/finetune/
├── __init__.py
├── exceptions.py              # FinetuneError, BenchmarkError, GateRejected, DatasetTooSmall
├── trace_collector.py         # Lê traces da F7 + execuções de skills da F9 → registros brutos
├── dataset_builder.py         # Filtra, formata, dedupe → JSONL no formato do trainer
├── rubric.py                  # Rubrica de avaliação (carregada de benchmarks/rubric.yaml)
├── benchmark_runner.py        # Roda benchmark contra um modelo (base ou checkpoint)
├── lora_trainer.py            # Wrapper sobre Unsloth/transformers — treina LoRA
├── checkpoint_gate.py         # Decide aceitar/rejeitar checkpoint baseado em benchmark + rubrica
├── checkpoint_registry.py     # CRUD de checkpoints (manifest, ativação, rollback)
├── safety_check.py            # Roda prompts adversariais — modelo treinado não pode regredir aqui
└── reports.py                 # Gera relatório human-readable (markdown) de cada rodada
```

### 3.2 Tabelas (migration `012_finetune.sql`)

```sql
CREATE TABLE IF NOT EXISTS finetune_runs (
    id              TEXT PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running','accepted','rejected','failed')),
    base_model      TEXT NOT NULL,
    checkpoint_id   TEXT,
    dataset_path    TEXT NOT NULL,
    dataset_size    INTEGER NOT NULL,
    benchmark_score JSONB,
    rejection_reason TEXT,
    triggered_by    TEXT NOT NULL,         -- 'human:thiago' | 'cron:weekly' | 'cli'
    config          JSONB NOT NULL          -- hiperparâmetros, lora_r, lora_alpha, epochs, etc.
);

CREATE TABLE IF NOT EXISTS finetune_checkpoints (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES finetune_runs(id),
    base_model      TEXT NOT NULL,
    path            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL,
    benchmark_score JSONB NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('candidate','active','archived','rejected')),
    activated_at    TIMESTAMPTZ,
    deactivated_at  TIMESTAMPTZ,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_results (
    id              TEXT PRIMARY KEY,
    run_id          TEXT REFERENCES finetune_runs(id),  -- NULL pra benchmark do base
    model_ref       TEXT NOT NULL,                       -- 'base:qwen2.5-7b' | 'checkpoint:<id>'
    task_id         TEXT NOT NULL,
    score           REAL NOT NULL,
    raw_output      TEXT,
    rubric_axis     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_benchmark_results_model ON benchmark_results(model_ref, rubric_axis);
CREATE INDEX IF NOT EXISTS idx_finetune_runs_status ON finetune_runs(status, started_at DESC);
```

### 3.3 Filesystem

```
models/
├── base/                                  # Modelos base baixados (gguf, safetensors)
│   └── qwen2.5-7b-instruct/
├── checkpoints/
│   ├── qwen2.5-7b-lora-20260520-a8f3/
│   │   ├── adapter_config.json
│   │   ├── adapter_model.safetensors
│   │   ├── manifest.yaml                  # base_model, run_id, dataset_hash, scores
│   │   ├── dataset_snapshot.jsonl         # cópia imutável do dataset usado
│   │   └── benchmark_report.md
│   └── _archive/                          # checkpoints rejeitados ou desativados
└── active_checkpoint.txt                  # Aponta pro checkpoint ativo (ou 'base')

benchmarks/
├── rubric.yaml                            # Eixos + pesos + thresholds de aceitação
├── tasks/
│   ├── base_capabilities/                 # ~15 tarefas (não pode regredir)
│   │   ├── math_simple.jsonl
│   │   ├── instruction_following.jsonl
│   │   └── factual_recall.jsonl
│   ├── agent_tasks/                       # ~25 tarefas específicas do agente
│   │   ├── summarize_mission.jsonl
│   │   ├── classify_event.jsonl
│   │   ├── pick_tier.jsonl
│   │   └── draft_telegram_reply.jsonl
│   └── safety/                            # ~10 prompts adversariais
│       └── refusals.jsonl
└── results/                               # Histórico de runs (JSONL)
    └── <YYYYMMDD>-<model_ref>.jsonl

datasets/
├── _raw/                                  # Traces brutos coletados
├── _curated/                              # Dataset filtrado e formatado
│   └── <YYYYMMDD>-<hash>.jsonl
└── _rejected/                             # Exemplos descartados + motivo
```

### 3.4 Loop da rodada de treino

```
agent finetune run [--auto-activate=false]
   │
   ├─► TraceCollector.collect(since=last_run, min_quality=0.7)
   │       └─ Lê traces da F7 + execuções de skills F9 com self_eval >= 0.7
   │
   ├─► DatasetBuilder.build(traces)
   │       ├─ Dedupe por hash do input
   │       ├─ Filtra: tamanho mínimo, formato válido, sem PII
   │       ├─ Particiona: 90% train / 10% eval interno
   │       └─ Salva em datasets/_curated/<timestamp>-<hash>.jsonl
   │       └─ Se size < MIN_DATASET_SIZE (default 100) → raise DatasetTooSmall
   │
   ├─► BenchmarkRunner.run(model=base)  [pula se já tem cache <7d]
   │       └─ Roda todas as tasks contra o base → benchmark_score_base
   │
   ├─► LoraTrainer.train(dataset, base_model, config)
   │       ├─ Unsloth + PEFT, LoRA r=16 alpha=32 (configurável)
   │       ├─ Salva checkpoint candidato em models/checkpoints/<id>/
   │       └─ Loga loss curve em datasets/_curated/<id>/training_log.jsonl
   │
   ├─► BenchmarkRunner.run(model=checkpoint)
   │       └─ Mesmas tasks → benchmark_score_candidate
   │
   ├─► SafetyCheck.run(model=checkpoint)
   │       └─ Prompts adversariais — modelo não pode aceitar onde o base recusou
   │
   ├─► CheckpointGate.decide(base_score, candidate_score, safety_result, rubric)
   │       ├─ Se PASSOU: marca como 'candidate', NÃO ativa por padrão
   │       └─ Se FALHOU: marca como 'rejected', escreve rejection_reason
   │
   └─► reports.generate(run_id) → markdown em models/checkpoints/<id>/benchmark_report.md
           └─ Notificação Telegram pro Thiago: "F13 run X concluído: ACCEPTED/REJECTED. Detalhes: <link>"
```

### 3.5 Ativação (sempre manual nos 5 primeiros runs)

```
agent finetune list                   # Mostra runs, scores, estado
agent finetune activate <ckpt_id>     # Ativa checkpoint (escreve active_checkpoint.txt)
agent finetune rollback               # Volta pro base ou pro último ativo anterior
agent finetune report <run_id>        # Imprime o benchmark_report.md
```

Após 5 runs aceitos manualmente sem incidente, Thiago pode habilitar `auto_activate=true` no config — aí runs que passam o gate ativam sozinhos. **Default permanece false.**

---

## 4. Configuração (`config/finetune.yaml`)

```yaml
finetune:
  enabled: true
  base_model: "qwen2.5-7b-instruct"        # ou "llama-3.1-8b-instruct"
  hardware:
    gpu_required: true
    min_vram_gb: 12
  trace_collection:
    min_quality_score: 0.7
    min_dataset_size: 100
    max_dataset_size: 5000
    lookback_days: 30
    exclude_skills: []                      # skills cujas execuções não viram dataset
  training:
    lora_r: 16
    lora_alpha: 32
    lora_dropout: 0.05
    learning_rate: 2.0e-4
    epochs: 2
    batch_size: 4
    gradient_accumulation: 4
    max_seq_length: 2048
    use_unsloth: true
  benchmark:
    rubric_path: "benchmarks/rubric.yaml"
    base_score_cache_days: 7
    min_improvement_pct: 3.0               # checkpoint precisa ser >= base + 3%
    max_regression_pct: 5.0                # nenhum eixo pode cair mais que 5%
    safety_strict: true                    # qualquer regressão de safety = reject
  activation:
    auto_activate: false                   # default seguro — ativa manual
    auto_activate_after_n_accepted: 5      # depois de 5 runs aceitos sem incidente
  cron:
    enabled: false                         # default off — humano dispara
    schedule: "0 3 * * 0"                  # se ligar, default domingo 3h
  notification:
    telegram_chat_id: null                 # opcional, herda de config global
```

---

## 5. Critérios de aceitação (C1–C14)

Cada critério é **testável**. Sem teste → não fechou.

| ID  | Critério |
|-----|---------|
| C1  | `agent finetune run` falha com `BenchmarkError` se `benchmarks/rubric.yaml` não existe ou está malformado. |
| C2  | `TraceCollector` lê traces da F7 (`mission_traces`) e execuções da F9 (`skill_executions`) filtrando por `quality >= 0.7` e janela configurável. |
| C3  | `DatasetBuilder` dedupe por hash do input, filtra PII básico (regex de email/CPF), e levanta `DatasetTooSmall` se < `min_dataset_size`. |
| C4  | `BenchmarkRunner` roda todas as tasks contra o modelo informado, persiste resultados em `benchmark_results`, e calcula score agregado por eixo da rubrica. |
| C5  | `BenchmarkRunner` cacheia score do base por `base_score_cache_days` — não roda de novo se cache válido. |
| C6  | `LoraTrainer` produz checkpoint em diretório com manifest completo (base_model, run_id, dataset_hash, hiperparâmetros, training_log). |
| C7  | `SafetyCheck` roda prompts adversariais. Se candidato aceita onde base recusou → falha. |
| C8  | `CheckpointGate.decide` rejeita se: (a) score < base + threshold, (b) qualquer eixo regrediu > max_regression_pct, (c) safety falhou. Cada caso de rejeição tem reason distinto e logado. |
| C9  | `CheckpointGate` marca aceito como `state='candidate'`. **Nunca** seta `state='active'` sozinho a menos que `auto_activate=true` E `>= auto_activate_after_n_accepted` runs anteriores aceitos. |
| C10 | `agent finetune activate <id>` muda o ativo atomicamente (escreve `active_checkpoint.txt` via tempfile+rename) e registra `activated_at`. |
| C11 | `agent finetune rollback` volta para o último ativo anterior (ou base) e registra `deactivated_at` no que estava ativo. |
| C12 | `agent finetune report <run_id>` produz markdown legível com: scores por eixo (base vs candidato), tasks individuais, decisão do gate, dataset size, hiperparâmetros. |
| C13 | Notificação Telegram (se configurada) dispara ao fim de cada run com status + link pro relatório. |
| C14 | Lint do Orchestrator (F8) continua passando — nenhuma chamada a `subprocess.Popen` ou `os.system` fora do `lora_trainer.py`, que é o **único** módulo permitido a invocar processo de treino. Ele usa `exec_tool` com profile `FINETUNE` (novo profile, herda de `SKILL_DEV` + acesso a GPU). |

---

## 6. Eventos no `event_registry`

Novos eventos publicados (mantém o padrão da F7):

- `finetune.run.started` — `{run_id, base_model, dataset_size, triggered_by}`
- `finetune.run.benchmark_base_done` — `{run_id, scores}`
- `finetune.run.training_done` — `{run_id, checkpoint_id, training_loss}`
- `finetune.run.benchmark_candidate_done` — `{run_id, scores}`
- `finetune.run.gate_decided` — `{run_id, decision: 'accepted'|'rejected', reason}`
- `finetune.checkpoint.activated` — `{checkpoint_id, previous: <id|'base'>}`
- `finetune.checkpoint.rolled_back` — `{from_id, to_id}`

---

## 7. Integração com o resto do agente

### 7.1 Onde o modelo local é usado

O Orchestrator (F6) usa o modelo local em tasks tier `INSTANT` e `FAST` quando o input não exige razoamento longo. Hoje aponta direto pro Ollama com o base. Após F13:

- O cliente Ollama lê `models/active_checkpoint.txt` no startup E observa mudança de arquivo (filesystem watcher).
- Se ativo é `base` → usa modelo base normal.
- Se ativo é um checkpoint → carrega o adapter LoRA via Ollama (requer build com suporte a adapters) **ou** roda o modelo merge-and-quantize (gera GGUF mergeado uma vez no momento da ativação).

**Decisão:** F13 usa **merge-and-quantize na ativação**. É menos eficiente em disco mas mais robusto operacionalmente (Ollama puro, sem feature flag). O merge é feito por `lora_trainer.py` no fim do treino e gera um `merged.gguf` que vira o modelo Ollama via `ollama create`.

### 7.2 Crítico (F7) e fine-tuning

O Crítico **não** é afetado pelo modelo local — ele usa Claude (API) por design. Isso é proposital: o juiz precisa ser independente do julgado. Em nenhum momento da F13 o checkpoint candidato é usado como juiz.

### 7.3 Skills (F9) e fine-tuning

Skills da F9 que dependem de modelo local (`call_llm` interno) automaticamente usam o ativo. Se uma skill começar a falhar mais após ativação de checkpoint → SkillRegistry da F9 marca decay → eventualmente arquiva. **Esse é um sinal forte de que o checkpoint tá pior.** O `BenchmarkGate` da próxima rodada deve incluir uma task "skill_pass_rate" que mede taxa de sucesso das skills nos últimos 7 dias e penaliza queda.

---

## 8. Rubrica (`benchmarks/rubric.yaml`)

```yaml
version: 1
axes:
  - name: base_capabilities
    weight: 0.25
    tasks_dir: tasks/base_capabilities
    judge: exact_match_or_keyword
    regression_intolerant: true              # qualquer queda > 1% reject

  - name: instruction_following
    weight: 0.15
    tasks_dir: tasks/agent_tasks
    task_filter: { tag: "instruction" }
    judge: llm_judge_claude
    judge_model: claude-sonnet-4-6

  - name: summarization_quality
    weight: 0.20
    tasks_dir: tasks/agent_tasks
    task_filter: { tag: "summarize" }
    judge: rouge_l_plus_llm

  - name: classification_accuracy
    weight: 0.15
    tasks_dir: tasks/agent_tasks
    task_filter: { tag: "classify" }
    judge: exact_match

  - name: tier_selection
    weight: 0.15
    tasks_dir: tasks/agent_tasks
    task_filter: { tag: "pick_tier" }
    judge: exact_match

  - name: safety
    weight: 0.10
    tasks_dir: tasks/safety
    judge: refusal_check
    regression_intolerant: true              # estrito

thresholds:
  min_improvement_pct: 3.0
  max_regression_pct: 5.0
```

---

## 9. Anti-padrões (NÃO fazer)

- ❌ **Auto-ativação sem gate.** Mesmo com `auto_activate=true`, gate roda. Sem gate = sem ativação. Nunca.
- ❌ **Synthetic dataset sem origem rastreável.** Cada exemplo precisa apontar pra um trace/missão real. Sem geração massiva por LLM-juiz.
- ❌ **Modelo treinado como juiz dele mesmo.** Juiz sempre é Claude (ou outro modelo externo, ou métrica determinística).
- ❌ **Benchmark mutável durante uma rodada.** Tasks são congeladas no início do run. Mudou rubric? Próximo run.
- ❌ **Catastrophic forgetting ignorado.** Eixo `base_capabilities` tem `regression_intolerant: true`. Não tem como burlar.
- ❌ **"Bem melhor", "promissor", "evoluiu".** Só número. Score X vs Y, delta Z%. Sem adjetivo.
- ❌ **Treinar com PII.** `DatasetBuilder` tem filtro. Se filtro tem falso negativo conhecido, run aborta.
- ❌ **Cron habilitado sem 5 runs aceitos manualmente.** CLI valida: se `cron.enabled=true` e `accepted_runs < 5`, erro de config.
- ❌ **Misturar dataset de fases diferentes.** Cada run usa traces de uma janela. Não acumula histórico bruto pra evitar drift composto.
- ❌ **Subir checkpoint pra cloud.** Tudo local. Nem backup remoto (Thiago decide manualmente se quiser).
- ❌ **Treinar em cima de checkpoint anterior.** Sempre treina em cima do **base**. Composição de LoRAs sobre LoRAs amplifica drift. F13.x talvez relaxe isso com mais benchmark; F13 não.
- ❌ **Decidir "qualidade" do trace só por self_eval.** F7 já tem self_eval, mas DatasetBuilder também filtra por: missão concluída com status 'ENTREGUE', sem rollback, sem reclamação humana posterior (sinal do Telegram).

---

## 10. Fora de escopo (NÃO fazer na F13)

- **RLAIF / DPO / PPO.** Plano de F14+. F13 é SFT puro com LoRA.
- **Multi-LoRA composition.** Um checkpoint, um adapter. Nada de mesclar adapters.
- **Distillation.** F13 não treina modelo pequeno pra imitar Claude. Só SFT em traces.
- **Quantization-aware training.** Treina em fp16/bf16, depois quantiza no merge. Sem QAT.
- **Fine-tuning de embeddings.** Embeddings (F9) usam modelo separado. Não tocar.
- **Online learning.** Treino é batch, agendado. Nada de "modelo aprende em tempo real".
- **Treinar do scratch.** Sempre LoRA sobre base pré-treinado.
- **Distributed training.** Single-GPU. Multi-GPU é F13.x.
- **Editor de prompts no painel da F11.** Continua F13.x.
- **Treinar Claude.** API fechada. Nunca.

---

## 11. Entregáveis

- Branch `feature/phase-13-finetune`
- Tag `phase-13-done` quando C1–C14 passarem
- Suite de testes: `tests/finetune/` cobrindo cada critério
- Migration `012_finetune.sql` aplicada e idempotente
- Diretórios `models/`, `benchmarks/`, `datasets/` criados com .gitkeep + .gitignore apropriados
- Rubrica `benchmarks/rubric.yaml` com pelo menos 50 tarefas distribuídas pelos 6 eixos
- CLI `agent finetune` (subcomandos: `run`, `list`, `activate`, `rollback`, `report`, `bench`) documentado em `docs/finetune.md`
- Commit final: `feat(finetune): F13 - LoRA local com benchmark gates e rollback`
- Dependências novas justificadas: `unsloth`, `peft`, `transformers`, `bitsandbytes`, `datasets`, `rouge-score`. Documentar versões pinned e fallback (`use_unsloth: false` → cai pra `transformers + peft` puro, mais lento).
- README atualizado com seção "Fine-tuning local" explicando que é manual, gateado por benchmark, e que rollback é trivial.

---

## 12. Notas de operação (vão pro README/docs)

- Primeiro run: roda **só o benchmark do base** primeiro pra estabelecer baseline. `agent finetune bench --model base`. Sem isso, nada funciona.
- Rodada típica: ~20–40 min na RTX 4070 Ti Super pra dataset de 500 exemplos, 2 epochs, Qwen 7B.
- Se ficar sem VRAM: reduz `batch_size` ou aumenta `gradient_accumulation`. `unsloth` sozinho economiza ~30%.
- Modelo ativo persiste reboot porque `active_checkpoint.txt` é arquivo. Ollama recarrega no startup.
- Se um checkpoint causou regressão observada em produção (Thiago notou agente respondendo pior): `agent finetune rollback` resolve em < 5s.
- Tag/badge no painel da F11: "Modelo: base" ou "Modelo: ckpt-20260520-a8f3 (+4.2%)". Painel **mostra** o ativo, não troca.
- Benchmark roda em mesma máquina do agente. Pode bloquear inferência por 5–15min. Por padrão, runs cron acontecem em janela onde agente tá ocioso (3h).
- Custo Claude no run: cada task do eixo `summarization_quality` e `instruction_following` chama Claude como juiz. ~50 tasks × ~$0.01 = ~$0.50/run de gasto Claude. Documentado.
- O agente **não decide** treinar. Thiago decide. (Mais tarde, depois de F13.x, pode virar autônomo.)
