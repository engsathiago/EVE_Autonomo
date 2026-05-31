# FASE D.5 — Re-validação F5 a F13 em Runtime Real

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Repo: `github.com/engsathiago/EVE_Autonomo`.
Pré-requisito: tag `fase-d1-done` empurrada.

## Objetivo único

Provar quais fases F5–F13 sobreviveram ao fix da Fase B + tool routing da Fase D.1, rodando smoke tests reais em runtime, NÃO em mock. Cada fase recebe veredito: **VALIDADA / PARCIAL / TEÓRICA / QUEBRADA**.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **NÃO maquia.** Se uma fase é TEÓRICA, escreve TEÓRICA. Sem "parcial" pra suavizar.
3. **NÃO conserta nada nesta fase.** Só valida e documenta. Correções vão pra fases posteriores ou `BUGS_ENCONTRADOS_D5.md`.
4. **Usa Ollama Cloud se Anthropic estiver rate-limited** (até 2026-06-01). Modelo: `qwen2.5:7b-instruct` ou equivalente do `.env`.
5. **Cada smoke test tem que produzir evidência DB.** Não basta o teste dizer "passou" — tem que ter registro em `tool_executions`, `subagent_runs`, `critic_evaluations`, `skill_invocations`, `channel_messages`, `mission_steps`, conforme a fase.

## Passos

### 1. Subir ambiente

```bash
cd ~/Desktop/agent
docker compose up -d postgres redis
sleep 5
docker compose ps
```

Se algo não subir, anota em `BUGS_ENCONTRADOS_D5.md` e tenta seguir com o que tem. Se Postgres falhar, aborta com tag `fase-d5-blocked`.

### 2. Baseline de contadores

```bash
docker compose exec postgres psql -U agent -d agent -c "
SELECT 'tool_executions' as t, count(*) FROM tool_executions
UNION ALL SELECT 'subagent_runs', count(*) FROM subagent_runs
UNION ALL SELECT 'critic_evaluations', count(*) FROM critic_evaluations
UNION ALL SELECT 'skill_invocations', count(*) FROM skill_invocations
UNION ALL SELECT 'channel_messages', count(*) FROM channel_messages
UNION ALL SELECT 'mission_steps', count(*) FROM mission_steps
UNION ALL SELECT 'sandbox_executions', count(*) FROM sandbox_executions;
" > D5_BASELINE.txt
```

Se alguma tabela não existir, anota em `BUGS_ENCONTRADOS_D5.md`.

### 3. Smoke test por fase

Pra cada fase abaixo, executa o teste, captura delta de contadores, classifica.

#### F5 — Gateway + Telegram
```bash
cd gateway && npm test -- --testPathPattern=telegram 2>&1 | tee /tmp/f5.log
# manual: posta mensagem fake via curl no endpoint do gateway
curl -X POST localhost:3000/webhook/telegram -H 'Content-Type: application/json' \
  -d '{"message":{"text":"teste F5","chat":{"id":1}}}' || echo "F5 endpoint indisponivel"
```
Esperado: incremento em `channel_messages`. Se não incrementar → TEÓRICA.

#### F6 — Cron + SubagentPool
```bash
cd ~/Desktop/agent
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.subagents.pool import SubagentPool
import asyncio
async def main():
    pool = SubagentPool(max_size=2)
    result = await pool.spawn_parallel(['echo hi', 'echo ho'])
    print(result)
asyncio.run(main())
" 2>&1 | tee /tmp/f6.log
```
Esperado: 2 entradas em `subagent_runs` com `actually_invoked_tools` não-nulo. Se zerado ou só prosa → TEÓRICA.

#### F7 — Conclave Critic
```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.critic.conclave import ConclaveCritic
import asyncio
async def main():
    critic = ConclaveCritic()
    verdict = await critic.evaluate('apagar todos os arquivos /tmp', irreversible=True)
    print(verdict)
asyncio.run(main())
" 2>&1 | tee /tmp/f7.log
```
Esperado: 1 entrada em `critic_evaluations` com as 3 personas registradas. Se só 1 persona ou nada → PARCIAL/TEÓRICA.

#### F8 — Sandbox
```bash
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.sandbox.executor import SandboxExecutor
result = SandboxExecutor(profile='DEFAULT').run('print(2+2)')
print(result)
" 2>&1 | tee /tmp/f8.log
```
Esperado: entrada em `sandbox_executions`. Se módulo importa mas não registra → PARCIAL.

#### F9 — Voyager skills
```bash
# tenta gerar skill após 5 ações similares simuladas
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.skills.voyager_generator import VoyagerSkillGenerator
import asyncio
async def main():
    gen = VoyagerSkillGenerator()
    actions = [{'tool':'web_search','args':{'q':f'test {i}'},'result':'ok'} for i in range(6)]
    skill = await gen.try_generate(actions)
    print(skill)
asyncio.run(main())
" 2>&1 | tee /tmp/f9.log
```
Esperado: arquivo `.md` novo em `skills/auto/` ou entrada `auto_generated=true` em `skills`. Se não → TEÓRICA (será refeito no prompt 04).

#### F10 — Deploy VPS
```bash
# verifica apenas se compose.prod.yml e scripts existem e validam
ls -la deploy/ docker-compose.prod.yml scripts/deploy.sh 2>&1 | tee /tmp/f10.log
docker compose -f docker-compose.prod.yml config > /dev/null 2>&1 && echo "compose VALIDO" || echo "compose QUEBRADO"
```
Esperado: arquivos existem, compose valida. Sem teste remoto (VPS pode estar suja). VALIDADA se arquivos OK.

#### F11 — Web UI
```bash
ls -la web/ ui/ frontend/ 2>&1 | tee /tmp/f11.log
# se existir, tenta build
if [ -d web ]; then cd web && (npm run build 2>&1 || echo "build FALHOU") ; cd ~/Desktop/agent; fi
```
Esperado: pasta existe e build passa. Quase certo que vai ser PARCIAL/TEÓRICA (prompt 05 vai refazer).

#### F12 — Canais extras
```bash
ls gateway/src/channels/ 2>&1 | tee /tmp/f12.log
```
Lista quais canais existem além do Telegram (Discord, WhatsApp, Slack). Cada um sem teste rodando = TEÓRICA.

#### F13 — LoRA fine-tuning
```bash
ls -la training/ lora/ unsloth/ 2>&1 | tee /tmp/f13.log
# verifica se existe ciclo já rodado
docker compose exec postgres psql -U agent -d agent -c \
  "SELECT count(*) FROM model_invocations WHERE model_name LIKE '%lora%' OR model_name LIKE '%ft-%';" \
  2>&1 | tee -a /tmp/f13.log
```
Esperado: scripts existem + pelo menos 1 invocação registrada. Sem invocação = TEÓRICA.

### 4. Delta de contadores

Mesma query do passo 2, salva em `D5_FINAL.txt`. Calcula delta linha a linha.

### 5. Gerar relatório

Cria `EXECUTION_AUDIT_POS_B.md` na raiz:

```markdown
# Re-validação F5–F13 pós Fase B + D.1

> Data: <hoje>
> Comparação: EXECUTION_AUDIT.md (pré-B) vs estado atual

## 1. Delta de contadores

| Tabela | Baseline | Final | Delta |
|---|---|---|---|
[preenche com os números reais]

## 2. Veredito por fase

| Fase | Pré-B | Pós-D.1 | Evidência | Próxima ação |
|---|---|---|---|---|
| F5 | TEÓRICA | ??? | channel_messages delta=N | ??? |
| F6 | TEÓRICA | ??? | subagent_runs delta=N | ??? |
| F7 | TEÓRICA | ??? | critic_evaluations delta=N | ??? |
| F8 | TEÓRICA | ??? | sandbox_executions delta=N | ??? |
| F9 | TEÓRICA | ??? | skills auto_generated delta=N | ??? |
| F10 | TEÓRICA | ??? | arquivos OK? | ??? |
| F11 | TEÓRICA | ??? | build passa? | ??? |
| F12 | TEÓRICA | ??? | canais ativos | ??? |
| F13 | TEÓRICA | ??? | LoRA invocations delta=N | ??? |

## 3. Bugs novos encontrados
[importa BUGS_ENCONTRADOS_D5.md]

## 4. Conclusão honesta

- N fases VALIDADAS
- M fases PARCIAIS
- K fases TEÓRICAS
- Z fases QUEBRADAS (regressões)

## 5. Recomendação

- Prompt 03 (D.4 Critic integration) é necessário? [sim/não]
- Prompt 04 (F9 voyager) é necessário? [sim/não]
- Prompt 05 (F11 Web UI) é refazer do zero ou ajustar? [refazer/ajustar]
- Prompt 07 (F13 LoRA) precisa rodar ciclo novo? [sim/não]
```

### 6. Commit

```bash
git add EXECUTION_AUDIT_POS_B.md D5_BASELINE.txt D5_FINAL.txt BUGS_ENCONTRADOS_D5.md
git commit -m "docs(d5): re-validação F5-F13 pós Fase B + D.1

Veredicto honesto: X validadas, Y parciais, Z teóricas, W quebradas.
Detalhes em EXECUTION_AUDIT_POS_B.md."
git tag fase-d5-done
git push origin main --tags
```

### 7. Relatório executivo

Cria `RELATORIO_D5.md`:

```markdown
# Relatório Fase D.5

## Resumo em 5 linhas
- Fases validadas: ___
- Fases parciais: ___
- Fases teóricas: ___
- Fases quebradas: ___
- Próximas correções necessárias: [lista curta]

## Próximo passo
Se F7 (Conclave) está TEÓRICA → cola prompt 03 (D.4 Critic integration).
Senão → pula direto pro 04 (F9).
```

## Critério de aceite

- `EXECUTION_AUDIT_POS_B.md` com tabela completa
- Tag `fase-d5-done` empurrada
- Nenhuma correção feita (essa fase é só diagnóstico)
- Cada fase F5–F13 tem veredito explícito

## NÃO faça

- Não conserta bug encontrado. Documenta e segue.
- Não roda novamente teste que passou (gasta API key).
- Não tenta deploy real na VPS aqui.
- Não pergunta nada.
