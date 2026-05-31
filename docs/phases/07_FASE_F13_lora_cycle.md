# FASE F13 — Ciclo LoRA Real com Benchmark

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-infra-done`.

## Objetivo único

Rodar UM ciclo completo de fine-tuning LoRA com Unsloth sobre dados reais do agente, com **benchmark before/after obrigatório**. Sem benchmark com diferença mensurável, ciclo é rejeitado.

## Regras duras (ESSENCIAIS — risco de model collapse)

1. **NÃO pergunta.** Decide e executa.
2. **NUNCA aceita modelo fine-tuned que piora no benchmark.** Reverter é obrigatório.
3. **Dataset mínimo: 200 exemplos reais.** Não gera dado sintético.
4. **Benchmark fixo, conhecido, externo.** MMLU subset ou HumanEval mini, NÃO um benchmark caseiro.
5. **Modelo base: qwen2.5:7b-instruct** (o que já está no `.env`).
6. **Hardware:** se não tem GPU local, usa Modal/RunPod com budget cap em USD 10. Se não dá → tag `fase-f13-blocked` e pula.

## Passos

### 1. Coletar dataset

Extrai conversas reais bem-sucedidas do agente:

```bash
docker compose exec postgres psql -U agent -d agent -c "
COPY (
  SELECT
    json_build_object(
      'messages', json_build_array(
        json_build_object('role','user','content', user_message),
        json_build_object('role','assistant','content', assistant_response)
      )
    ) AS jsonl
  FROM channel_messages cm
  JOIN mission_steps ms ON ms.message_id = cm.id
  WHERE ms.status = 'completed'
    AND ms.created_at > NOW() - INTERVAL '60 days'
  LIMIT 500
) TO STDOUT;
" > training/data/real_conversations.jsonl
```

Se não tem 200 exemplos → tag `fase-f13-blocked`, documenta em `BUGS_ENCONTRADOS_F13.md`, segue pro prompt 08.

### 2. Split treino/eval

```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
import json, random
random.seed(42)
data = [json.loads(l) for l in open('training/data/real_conversations.jsonl')]
random.shuffle(data)
n = len(data)
train = data[:int(n*0.9)]
val = data[int(n*0.9):]
with open('training/data/train.jsonl','w') as f:
    for ex in train: f.write(json.dumps(ex)+'\n')
with open('training/data/val.jsonl','w') as f:
    for ex in val: f.write(json.dumps(ex)+'\n')
print(f'train={len(train)} val={len(val)}')
"
```

### 3. Benchmark BEFORE

Cria `training/benchmark.py`:

```python
"""Benchmark fixo: 50 perguntas MMLU-PT + 20 tarefas de tool use sintéticas."""
import json
from pathlib import Path
import asyncio

QUESTIONS = json.loads((Path(__file__).parent / "benchmark_questions.json").read_text())

async def run_benchmark(model_invoker) -> dict:
    correct = 0
    for q in QUESTIONS:
        ans = await model_invoker(q["prompt"])
        if q["expected_substring"].lower() in ans.lower():
            correct += 1
    return {
        "total": len(QUESTIONS),
        "correct": correct,
        "accuracy": correct / len(QUESTIONS),
    }
```

Cria `training/benchmark_questions.json` com 70 entradas (mistura MMLU-PT subset + tarefas de tool use que o agente deveria saber).

Roda baseline:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
import asyncio
from training.benchmark import run_benchmark
from agent.transport.ollama import OllamaTransport
async def main():
    t = OllamaTransport(model='qwen2.5:7b-instruct')
    r = await run_benchmark(lambda p: t.complete(p))
    print('BASELINE:', r)
    import json
    json.dump(r, open('training/results/baseline.json','w'), indent=2)
asyncio.run(main())
"
```

### 4. Fine-tuning

Cria `training/train_lora.py`:

```python
"""Treino LoRA com Unsloth sobre dataset real."""
from unsloth import FastLanguageModel
import torch

MODEL = "unsloth/Qwen2.5-7B-Instruct"
OUTPUT = "training/output/eve-lora-v1"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL,
    max_seq_length=2048,
    load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
)

# carrega train.jsonl, formata, treina por 1 epoch
# ... código padrão Unsloth ...

model.save_pretrained(OUTPUT)
tokenizer.save_pretrained(OUTPUT)
```

Roda. Se hardware local não dá → cria script `training/run_on_modal.py` com budget cap.

### 5. Benchmark AFTER

Carrega modelo treinado e roda mesmo benchmark:

```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
import asyncio, json
from training.benchmark import run_benchmark
from training.eval_adapter import FineTunedInvoker
async def main():
    inv = FineTunedInvoker('training/output/eve-lora-v1')
    r = await run_benchmark(inv)
    print('AFTER:', r)
    json.dump(r, open('training/results/after.json','w'), indent=2)
asyncio.run(main())
"
```

### 6. Decisão

```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
import json
b = json.load(open('training/results/baseline.json'))
a = json.load(open('training/results/after.json'))
delta = a['accuracy'] - b['accuracy']
print(f'baseline={b[\"accuracy\"]:.3f} after={a[\"accuracy\"]:.3f} delta={delta:+.3f}')
if delta < 0.01:
    print('REJEITADO: melhoria <1%')
    exit(1)
print('ACEITO')
"
```

Se rejeitado:
- Documenta em `RELATORIO_F13.md` com baseline/after/delta
- NÃO promove o modelo
- Tag `fase-f13-blocked` (não `f13-done`)
- Próxima sessão decide se vale tentar com mais dados ou desistir

Se aceito:
- Registra em `model_invocations` rows novos com `model_name='eve-lora-v1'`
- Atualiza `.env` setando uma das tasks pra usar o LoRA
- Tag `fase-f13-real-done`

### 7. Commit + tag + push

```bash
git add -A
# adiciona .gitignore pra pesos do modelo (não commitar GB)
echo "training/output/" >> .gitignore
echo "training/data/*.jsonl" >> .gitignore
git add .gitignore

git commit -m "feat(f13): ciclo LoRA real com benchmark before/after

- 70 perguntas benchmark fixo (MMLU-PT subset + tool use)
- Baseline accuracy: X.XX
- After accuracy: Y.YY (delta: ZZZ)
- Modelo: [aceito/rejeitado]
- Dataset: N exemplos reais de channel_messages
- Pesos em training/output/ (gitignored)

Resolve: F13 do roadmap"

git tag fase-f13-real-done   # ou fase-f13-blocked se rejeitado
git push origin main --tags
```

### 8. Relatório

`RELATORIO_F13.md`:
```markdown
# Relatório Fase F13
- Dataset: N exemplos reais
- Baseline accuracy: X.XX
- After accuracy: Y.YY
- Delta: ZZZ
- Veredito: [ACEITO / REJEITADO]
- Custo (se Modal/RunPod): USD __
- Próximo: 08_FASE_CLEANUP_vps_docs.md
```

## Critério de aceite

- `training/results/baseline.json` e `after.json` existem
- Delta calculado e documentado
- Se aceito: tag `fase-f13-real-done`
- Se rejeitado: tag `fase-f13-blocked` e modelo NÃO promovido

## Quando pular esta fase

Se qualquer um dos seguintes:
- Não tem 200 exemplos reais
- Não tem GPU local nem budget pra Modal/RunPod
- Benchmark mostra que modelo base já está saturado pro nosso uso

→ Tag `fase-f13-skipped`, documenta motivo, segue pro 08.

## NÃO faça

- NUNCA gera dados sintéticos pra inflar dataset.
- NUNCA aceita modelo que piora (mesmo "só um pouco").
- NUNCA commita pesos do modelo (GB).
- Não pergunta nada.
