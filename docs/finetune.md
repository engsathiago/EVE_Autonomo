# Fine-tuning Local (F13) — Runbook

Fine-tuning periódico do modelo local (Qwen 2.5 / Llama 3.x) com LoRA.
**Sem benchmark aprovado, nenhum checkpoint é ativado.** Essa é a regra inegociável da F13.

---

## Pré-requisitos

- GPU NVIDIA com ≥ 12 GiB VRAM (ex: RTX 4070 Ti Super = 16 GiB)
- Ollama instalado e rodando (`ollama serve`)
- Modelo base baixado no Ollama:
  ```bash
  ollama pull qwen2.5:7b-instruct
  ```
- Dependências extras instaladas:
  ```bash
  pip install 'agent-core[finetune]'
  ```
- `config/finetune.yaml` configurado (já criado com defaults sãos)

---

## Primeira execução — estabelecer baseline

Antes do primeiro treino, é obrigatório estabelecer o score de base:

```bash
agent finetune bench --model base
```

Isso roda todas as 62 tasks do benchmark contra o modelo base e persiste os
resultados em `benchmark_results`. O score é cacheado por 7 dias.

Sem baseline, `agent finetune run` falha com `BenchmarkError` explícito.

---

## Executar um ciclo de fine-tuning

```bash
agent finetune run
```

Fluxo completo:
1. Coleta traces (missões + skills dos últimos 30 dias)
2. Constrói dataset JSONL deduplicado e filtrado de PII
3. Benchmark do modelo base (usa cache se < 7 dias)
4. Treino LoRA com Unsloth (fallback: transformers+peft)
5. Benchmark do candidato
6. Safety check (12 prompts adversariais)
7. Gate decide: APROVADO ou REJEITADO
8. Relatório gerado em `models/checkpoints/<id>/benchmark_report.md`
9. Notificação Telegram (se configurado)

**Tempo típico:** 20–40 minutos na RTX 4070 Ti Super para dataset de 500 exemplos,
2 epochs, Qwen 7B.

### Flags úteis

```bash
agent finetune run --dry-run          # só coleta e exibe stats do dataset, sem treinar
agent finetune run --triggered-by cron:weekly
```

---

## Ver resultados

```bash
agent finetune list                   # últimos runs com status e delta de score
agent finetune report <run_id>        # markdown completo de um run
```

---

## Ativar um checkpoint

Por padrão, checkpoints aprovados ficam no estado `candidate`. Para ativar:

```bash
agent finetune activate <checkpoint_id>
```

Isso escreve `models/active_checkpoint.txt` atomicamente (tempfile + rename).
O Ollama usa esse arquivo no startup para carregar o modelo certo.

**Após 5 ativações manuais sem incidente**, você pode habilitar auto-ativação:

```yaml
# config/finetune.yaml
activation:
  auto_activate: true
  auto_activate_after_n_accepted: 5
```

---

## Rollback

Se um checkpoint causou regressão observada em produção:

```bash
agent finetune rollback
```

Volta para o último ativo anterior (ou `base` se nenhum). Resolve em < 5 segundos.

---

## Troubleshooting VRAM

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `CUDA out of memory` | batch_size muito alto | Reduza `batch_size: 4` → `2` |
| Treino muito lento | `use_unsloth: false` | Instale unsloth e mude para `true` |
| OOM no merge | Modelo 13B+ | Use modelo 7B ou mais RAM de sistema |
| `TrainerNotAvailable` | nvidia-smi não encontrado | Verificar drivers NVIDIA |

Para economizar VRAM com Unsloth: o framework usa ~30% menos que transformers puro.
Configuração conservadora para 12 GiB:
```yaml
training:
  batch_size: 2
  gradient_accumulation: 8
  lora_r: 8
```

---

## Custo Claude por run

O benchmark usa Claude como juiz nos eixos `instruction_following` e `summarization_quality`.

| Eixo | Tasks | Tokens estimados/task | Custo estimado |
|------|-------|----------------------|----------------|
| instruction_following | ~11 tasks | ~800 tokens | ~$0.02 |
| summarization_quality | ~10 tasks | ~1.200 tokens | ~$0.04 |
| **Total por run** | ~21 calls | — | **~$0.06–0.10** |

Custo por run: aproximadamente **$0.06 a $0.10** com claude-sonnet-4-6.

---

## Estrutura de arquivos

```
benchmarks/
├── rubric.yaml                  # eixos + pesos + thresholds
├── tasks/
│   ├── base_capabilities/       # 22 tasks (não pode regredir)
│   ├── agent_tasks/             # 28 tasks (summarize, classify, pick_tier, draft)
│   └── safety/                  # 12 tasks adversariais
└── results/                     # histórico JSONL

datasets/
├── _raw/                        # traces brutos (gitignored)
├── _curated/                    # dataset filtrado (gitignored, imutável após criação)
└── _rejected/                   # exemplos descartados (gitignored)

models/
├── base/                        # modelos base baixados (gitignored)
├── checkpoints/                 # checkpoints LoRA (gitignored)
└── active_checkpoint.txt        # aponta para o ativo (ou 'base')
```

---

## Schema do rubric.yaml

```yaml
version: 1         # sempre 1 por enquanto
axes:
  - name: nome_do_eixo
    weight: 0.25   # pesos devem somar 1.0
    tasks_dir: tasks/subdir     # relativo a benchmarks/
    judge: exact_match          # ou exact_match_or_keyword, llm_judge_claude,
                                #    rouge_l_plus_llm, refusal_check
    judge_model: claude-sonnet-4-6  # para juízes LLM
    task_filter:
      tag: "pick_tier"          # filtra tasks pela tag
    regression_intolerant: true # qualquer queda > 1% = reject imediato

thresholds:
  min_improvement_pct: 3.0
  max_regression_pct: 5.0
```

## Schema de task JSONL

```json
{
  "id": "task_001",
  "prompt": "Texto da pergunta",
  "expected": "Resposta esperada",
  "keywords": ["keyword1", "keyword2"],
  "tags": ["classify", "error"],
  "source": "handwritten"
}
```

Campos obrigatórios: `id`, `prompt`, `expected`.

---

## Anti-padrões (não fazer)

- ❌ Ativar checkpoint sem ler o relatório primeiro
- ❌ Modificar `benchmarks/rubric.yaml` durante um run ativo
- ❌ Adicionar exemplos manualmente ao `_curated/` (é imutável por design)
- ❌ Habilitar cron antes de 5 ativações manuais sem incidente
- ❌ Treinar sobre checkpoint anterior (sempre sobre o base)
