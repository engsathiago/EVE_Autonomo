# Referência da CLI

A EVE inclui uma CLI completa construída com [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/).

## Instalação

```bash
cd cli
pip install -e .
```

Ou, se o Core já estiver instalado:
```bash
pip install -e "./core" -e "./cli"
```

## Uso geral

```bash
agent --help          # Ver todos os comandos
agent --version       # Versão
agent setup           # Validar configuração
```

---

## agent run

Envia uma mensagem para o agente e recebe a resposta.

```bash
agent run "Qual é o status do deploy?"
agent run --model ollama:qwen2.5:7b "Resuma esse texto"
agent run --conversation-id abc-123 "Continue de onde paramos"
```

| Flag | Descrição |
|------|-----------|
| `--model` | Override do modelo (ex: `anthropic:claude-sonnet-4-6`) |
| `--conversation-id` | Retomar conversa existente |

---

## agent skill

Gerencia skills do agente.

```bash
agent skill list                          # Listar todas as skills
agent skill show <name>                   # Ver detalhes de uma skill
agent skill run <name>                    # Executar skill manualmente
agent skill validate <name>               # Validar sintaxe da skill
agent skill review <name>                 # Revisar skill com LLM
agent skill create-from-session <id>      # Criar skill a partir de sessão
```

---

## agent model

Gerencia providers e modelos de LLM.

```bash
agent model list                          # Listar modelos configurados
agent model health                        # Status de cada provider
agent model show <provider:model>         # Detalhes de um modelo
agent model test <provider:model> "Olá"   # Testar modelo com prompt
agent model costs --since today           # Ver gastos
agent model costs --since 2026-05-01      # Gastos desde uma data
```

---

## agent cron

Gerencia tarefas agendadas.

```bash
agent cron add "toda segunda às 9h" "Checar PRs"     # Criar job
agent cron list                                        # Listar jobs
agent cron show <job_id>                               # Detalhes do job
agent cron enable <job_id>                             # Habilitar job
agent cron disable <job_id>                            # Desabilitar job
agent cron remove <job_id>                             # Remover job
agent cron run-now <job_id>                            # Executar agora
```

O primeiro argumento do `add` aceita linguagem natural em português ou inglês. O agente converte automaticamente para cron expression.

---

## agent task

Gerencia tasks e subagent runs.

```bash
agent task list                           # Listar tasks recentes
agent task show <task_id>                 # Detalhes da task
agent task tree <task_id>                 # Árvore hierárquica
agent task cancel <task_id>               # Cancelar task em andamento
agent task stats                          # Estatísticas do orquestrador
```

---

## agent mission

Gerencia missões de longo prazo.

```bash
agent mission create "Migrar para v2"     # Criar missão
agent mission list                         # Listar missões
agent mission show <mission_id>            # Detalhes + steps
agent mission pause <mission_id>           # Pausar missão
agent mission resume <mission_id>          # Retomar missão
agent mission replan <mission_id>          # Replanejar steps
agent mission reflect <mission_id>         # Forçar reflexão
```

---

## agent critic

Consulta o crítico autônomo.

```bash
agent critic history                       # Últimas avaliações
agent critic stats                         # Estatísticas gerais
```

---

## agent memory

Gerencia memória do agente.

```bash
# Memória reflexiva
agent memory reflexive list               # Listar insights
agent memory reflexive search "schema"    # Buscar insight
agent memory reflexive delete <id>        # Remover insight
```

---

## agent loop

Controla o loop autônomo.

```bash
agent loop status                          # Estado atual
agent loop pause                           # Pausar
agent loop resume                          # Retomar
agent loop tick                            # Forçar tick manual
```

---

## agent web

Controla o web dashboard.

```bash
agent web start                            # Iniciar servidor web
agent web status                           # Status do servidor
```

---

## agent finetune

Gerencia fine-tuning local (LoRA).

```bash
agent finetune run                         # Executar ciclo completo
agent finetune bench --model base          # Benchmark do modelo base
agent finetune list                        # Listar runs anteriores
agent finetune report <run_id>             # Relatório detalhado
agent finetune activate <checkpoint_id>    # Ativar checkpoint
agent finetune rollback                    # Reverter para modelo anterior
```

---

## Variáveis de Ambiente

A CLI respeita as mesmas variáveis do Core:

| Variável | Usada por |
|----------|-----------|
| `ANTHROPIC_API_KEY` | `agent run`, `agent model test` |
| `POSTGRES_URL` | Todas as operações com banco |
| `REDIS_URL` | Operações que usam pubsub |
| `DEFAULT_MODEL` | `agent run` (se não especificar `--model`) |

---

## Exemplos de Uso

### Fluxo completo de uma missão

```bash
# 1. Criar missão
agent mission create "Implementar sistema de cache com Redis"

# 2. Acompanhar progresso
agent mission show <id>

# 3. Ver tasks geradas
agent task list

# 4. Pausar se necessário
agent mission pause <id>

# 5. Retomar
agent mission resume <id>
```

### Agendar relatório diário

```bash
# Agendar
agent cron add "todo dia às 8h" "Gerar relatório de métricas do dia anterior"

# Verificar
agent cron list

# Testar antes
agent cron run-now <job_id>
```

### Verificar custos

```bash
# Gastos de hoje
agent model costs --since today

# Gastos da semana
agent model costs --since 2026-05-10

# Health de todos os providers
agent model health
```
