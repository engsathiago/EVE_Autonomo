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
```

---

## 🆕 agent init — Wizard de configuração (estilo OpenClaw/Hermes)

Setup interativo completo em ~2 minutos. Pergunta provider, modelo, chave de API, testa conexão, grava `.env`.

```bash
agent init                   # Wizard interativo
agent init --force           # Sobrescreve .env existente
agent init --env-path ./.env.prod   # Aponta para outro arquivo
```

**O que ele faz:**
1. Mostra os 5 providers disponíveis (Ollama Cloud, Ollama Local, Anthropic, OpenAI, OpenRouter)
2. Você escolhe um e o modelo padrão dele
3. Pede a API key (se aplicável)
4. **Testa a conexão antes de salvar**
5. Pergunta config do Postgres (Docker ou bare-metal)
6. Mostra resumo e pede confirmação
7. Grava o `.env` completo

---

## 🆕 agent config — Gerenciar configuração (estilo OpenClaw)

```bash
agent config show                       # Estado atual completo (com keys mascaradas)
agent config use ollama:gpt-oss:120b   # Trocar modelo padrão
agent config set MODEL_TIMEOUT_S 180    # Mudar qualquer variável
agent config get DEFAULT_MODEL          # Ler valor de uma variável
agent config models                     # Listar modelos de todos os providers ativos
agent config providers                  # Status de cada provider
```

**Exemplo prático — trocar de Claude para Ollama Cloud:**

```bash
agent config set OLLAMA_API_KEY ollama_xxx
agent config set OLLAMA_BASE_URL https://ollama.com
agent config use ollama:gpt-oss:120b
docker compose restart core
```

---

## 🆕 agent status — Dashboard (estilo Hermes)

```bash
agent status                # Visão geral (provider, infra, métricas 24h)
agent status --detailed     # Inclui últimas 5 chamadas LLM
```

**Mostra de uma só vez:**
- Configuração ativa (modelo, fallback, timeouts)
- Health: Postgres, Redis, Core HTTP, Gateway HTTP
- Health de cada provider de LLM configurado
- Estatísticas das últimas 24h (mensagens, tokens, custo, missões, aprovações)

---

## 🆕 agent chat (ou `eve`) — TUI interativo estilo OpenClaw

Abre uma interface de chat rica no terminal, com:
- Banner permanente mostrando modelo, mensagens, tokens, custo, tempo
- Auto-complete de comandos
- Histórico persistente entre sessões
- Renderização Markdown nas respostas
- 12 slash commands

```bash
agent chat                            # Abre com modelo padrão
agent chat --model ollama:gpt-oss:120b   # Override de modelo
eve                                   # Atalho dedicado (após pip install)
```

**Slash commands disponíveis dentro do chat:**

| Comando | Descrição |
|---------|-----------|
| `/help` | Lista todos os comandos |
| `/model` | Mostra o modelo atual |
| `/model <novo>` | Troca o modelo **ao vivo** (sem sair) |
| `/clear` | Limpa a tela |
| `/cost` | Mostra total de tokens/custo da sessão |
| `/tools` | Lista tools disponíveis |
| `/skills` | Lista skills carregadas |
| `/missions` | Lista missões ativas |
| `/approvals` | Lista aprovações pendentes |
| `/save [arquivo.md]` | Salva a conversa em Markdown |
| `/reset` | Zera contadores de tokens/custo |
| `/exit` (ou Ctrl+D) | Sai do chat |

**Exemplo de sessão:**

```
╭──────────────────────────────────────────╮
│ EVE — Agente Autônomo  | modelo: ollama:gpt-oss:120b
│ Digite /help para comandos · /exit para sair
╰──────────────────────────────────────────╯

› Liste os arquivos do projeto

  🔧 list_dir(path=.)
     ↳ 12 itens

  EVE  No diretório raiz tem: core/, gateway/, cli/, webui/, docs/...

  ─ 2 iter · 1,250 tokens · $0.0012 · 1.8s ─

› /model ollama:deepseek-v3.1:671b-cloud
  ✓ Modelo trocado: ollama:gpt-oss:120b → ollama:deepseek-v3.1:671b-cloud

› /cost
  Mensagens: 1 · Tokens: 1,250 · $0.0012

› /exit
  Até logo! 👋
```

---

## 🆕 agent doctor — Diagnóstico

```bash
agent doctor                # Roda 11 checks e reporta o que está OK/quebrado
```

**Checks executados:**
1. Versão do Python (3.11+)
2. `.env` existe
3. Config carrega sem erro
4. Pelo menos 1 provider LLM configurado
5. `DEFAULT_MODEL` é válido e tem key correspondente
6. Postgres conecta
7. Redis conecta
8. Provider ativo responde
9. Migrações aplicadas (tabelas críticas presentes)
10. Docker instalado (opcional)
11. Workspace paths acessíveis

Exit code 0 = tudo OK. Exit code 1 = problemas.

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
