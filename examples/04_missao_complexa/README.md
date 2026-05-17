# 04 — Missão Complexa Multi-Step

Missões são tarefas de longo prazo que a EVE executa de forma autônoma, com planejamento, reflexão e replanejamento.

## Diferença entre `run` e `mission`

| `agent run` | `agent mission` |
|-------------|-----------------|
| 1 goal, 1 sessão | Goal grande dividido em N steps |
| Síncrono | Assíncrono, persiste no banco |
| Máx 15 iterações | Sem limite (interrompível) |
| Memória de curto prazo | Reflexão entre steps |

## Caso de uso

> "Quero que a EVE migre meu schema do banco para a v2, mantendo backward compatibility, com testes e rollback plan."

Isso é uma **missão**, não uma conversa.

## 1. Criar a missão

```bash
agent mission create "Migrar schema do banco para v2 mantendo backward compatibility, com testes e rollback plan."
```

Saída:

```
✨ Missão criada: m_abc123
📋 Planejamento gerado:

  1. Analisar schema atual e documentar dependências
  2. [PARALELO 2] Escrever migration up + Escrever migration down
  3. Criar testes para a migration up
  4. Criar testes para o rollback (migration down)
  5. Executar migrations em ambiente de staging
  6. Validar resultado com testes E2E
  7. Documentar plano de rollback em produção

Status: active | Steps: 7 | Próximo: step 1
```

Note o `[PARALELO 2]` — a EVE identifica steps independentes e os executa em paralelo via subagentes.

## 2. Acompanhar progresso

```bash
agent mission show m_abc123
```

```
Missão m_abc123
Status: active
Step atual: 3 de 7

✅ Step 1: Analisar schema atual (concluído)
✅ Step 2: Escrever migration up + down (paralelo, concluído)
🔄 Step 3: Criar testes para a migration up (em andamento)
⏳ Step 4-7: aguardando

💭 Última reflexão (após step 2):
"Os dois migrations foram criados e validados. A up cria
nova tabela audit_logs e a down a remove com rollback de
dados. Próximo step: cobertura de testes."
```

## 3. Pausar/Retomar

```bash
agent mission pause m_abc123   # Pausa após o step atual
agent mission resume m_abc123  # Retoma
```

## 4. Replanejar

Se o contexto mudar:

```bash
agent mission replan m_abc123
```

O planner regenera os steps restantes considerando o que já foi feito.

## 5. Refletir manualmente

```bash
agent mission reflect m_abc123
```

Força a EVE a refletir e atualizar a memória reflexiva, mesmo sem completar um step.

## Como funciona internamente

```
┌─────────────────────────────────────┐
│ MissionPlanner (Haiku)              │
│ goal → steps[]                       │
└─────────────┬───────────────────────┘
              ▼
┌─────────────────────────────────────┐
│ AutonomousLoop (tick a cada 5min)   │
│ Pega missão active → próximo step    │
└─────────────┬───────────────────────┘
              ▼
┌─────────────────────────────────────┐
│ AIAgent executa step                │
│ (até 3 steps por tick)              │
└─────────────┬───────────────────────┘
              ▼
┌─────────────────────────────────────┐
│ Critic avalia (3 personas)          │
│ - Técnico                            │
│ - Advogado do diabo                  │
│ - Sintetizador → decisão final       │
└─────────────┬───────────────────────┘
              ▼
┌─────────────────────────────────────┐
│ MissionReflector (Sonnet)           │
│ Insight → reflexive_memory          │
└──────────────────────────────────────┘
```

## Steps paralelos `[PARALELO N]`

Quando o planner identifica steps independentes, ele os marca com `[PARALELO N]`. A EVE então:

1. Solicita N subagentes ao `SubagentPool`
2. Distribui os steps entre eles
3. Aguarda com `asyncio.gather` (timeout hard)
4. Agrega resultados via `Aggregator`

Cada subagente roda em isolamento total (sem acesso a memory_store, conversation fresh).

## Próximo passo

[05_plugin_custom_tool](../05_plugin_custom_tool/) — Desenvolva sua própria tool como plugin.
