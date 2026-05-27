# 06 — Workflow de Fine-tuning Local

Como ensinar à EVE algo novo sem mudar prompts — via LoRA fine-tuning sobre modelo local.

⚠️ **Pré-requisito de hardware:** GPU NVIDIA com 12+ GB VRAM (testado em RTX 4070 Ti Super 16GB). Sem GPU, o treino não roda.

## Quando fazer fine-tuning?

✅ **Bom para:**
- Especializar em domínio específico (ex: finanças, medicina, jurídico)
- Reduzir custo migrando tarefas frequentes para modelo local
- Alinhar tom/estilo a uma marca ou perfil
- Memorizar padrões repetitivos (ex: formato de resposta de email corporativo)

❌ **Ruim para:**
- Substituir busca em memória semântica
- Ensinar fatos novos (use a memória reflexiva)
- Resolver bugs no agente (corrija o código)

## Instalação das dependências

```bash
pip install "agent-core[finetune]"
# Inclui: unsloth, peft, transformers, bitsandbytes, datasets, rouge-score
```

## 1. Estabelecer baseline

Antes de qualquer treino, meça o modelo base:

```bash
agent finetune bench --model base
```

Saída:

```
🎯 Benchmark do modelo base: qwen2.5:7b-instruct

📊 Resultados (62 tasks em 6 eixos):
  • factual_recall:         78.3%
  • instruction_following:  82.1%
  • math_simple:            74.5%
  • classify_event:         85.7%
  • summarize_mission:      71.2%
  • safety:                 96.4%

Overall: 81.4% | Cached por 7 dias
```

## 2. Executar ciclo de fine-tuning

```bash
agent finetune run
```

Isso dispara o pipeline completo:

```
┌─────────────────────────────────────────────────┐
│ 1. TraceCollector                               │
│    Coleta traces dos últimos 30 dias            │
│    - Missões (F7): success=True, score >= 0.7   │
│    - Skills (F9): bem-sucedidas                 │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ 2. DatasetBuilder                               │
│    - Filtro PII (email, CPF, telefone)          │
│    - Deduplicação                               │
│    - Particionamento 90/10                      │
│    - Output: JSONL imutável                     │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ 3. LoRATrainer (Unsloth + QLoRA 4-bit)          │
│    - Base: qwen2.5:7b-instruct                  │
│    - 3 epochs, lr=2e-4                          │
│    - Output: adapter + merged GGUF              │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ 4. SafetyCheck                                  │
│    - 20 prompts adversariais                    │
│    - Compara base vs candidato                  │
│    - REJEITA se safety regrediu                 │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ 5. BenchmarkRunner                              │
│    - 62 tasks, 6 eixos                          │
│    - Juiz: Claude Sonnet                        │
└──────────────┬──────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────┐
│ 6. CheckpointGate                               │
│    Gates:                                       │
│    1. safety_check: PASS                        │
│    2. per_axis: nenhum eixo regride > 5%        │
│    3. overall: score >= base + 3%               │
│    Se TODOS passarem: candidato aprovado        │
└─────────────────────────────────────────────────┘
```

Tempo total: ~45 min em RTX 4070 Ti Super, ~2.5 GB VRAM em uso.

## 3. Ver resultado

```bash
agent finetune list
```

```
ID         | Data       | Status    | Overall | vs Base
ft_001     | 2026-05-15 | approved  | 85.2%   | +3.8%
ft_002     | 2026-05-08 | rejected  | 80.1%   | -1.3%   (math regrediu 7%)
ft_003     | 2026-05-01 | approved  | 84.1%   | +2.7%
```

Detalhes:

```bash
agent finetune report ft_001
```

Gera markdown com:
- Scores por eixo (antes/depois)
- Configuração de treino
- Amostras de respostas
- Resultado do safety check
- Decisão do gate

## 4. Ativar o checkpoint

⚠️ **Importante:** Ativação é **manual** nas 5 primeiras rodadas. Depois pode ser automatizada via config.

```bash
agent finetune activate ft_001
```

O `CheckpointRegistry` atualiza o ponteiro `current_model` atomicamente (tempfile + rename) e dispara um evento `finetune.activated`.

## 5. Verificar em produção

```bash
agent run --model ollama:eve-custom "Resuma essa missão: ..."
```

A EVE usa o checkpoint ativado.

## 6. Rollback (se algo der errado)

```bash
agent finetune rollback
```

Volta atomicamente para o checkpoint anterior. Sem downtime.

## Custos

Cada ciclo de fine-tuning:
- **Compute local:** ~45 min de GPU (grátis se for sua máquina)
- **Claude (juiz do benchmark):** ~$2-5 por run (Sonnet × 62 tasks × 2 passes)
- **Storage:** ~5 GB por checkpoint (adapter + GGUF merged)

## Frequência recomendada

- **Inicialmente:** 1× por semana, com revisão manual
- **Estável:** 1× por mês, ativação automática se overall >= base + 5%

## Troubleshooting

### CUDA out of memory

```bash
# Reduza batch_size em config/finetune.yaml
batch_size: 1
gradient_accumulation_steps: 8
```

### Dataset muito pequeno

```bash
# Mínimo: 100 amostras. Se < 100:
agent finetune run --force-min-dataset 50
# Ou rode missões/skills mais até acumular traces
```

### Modelo base não existe no Ollama

```bash
ollama pull qwen2.5:7b-instruct
```

## Próximos passos

Voltar para [examples/](../) ou ver [docs/finetune.md](../../docs/finetune.md) para o runbook completo.
