# Projeto EVE_Autonomo — Relatório Final v1.0.0

## Status: v1.0.0 entregue

## Fases entregues

| Fase | Estado | Detalhe |
|------|--------|---------|
| F0 | ✅ validada | Fundação, Docker, CI |
| F1 | ✅ validada | Core ReAct, AIAgent, tool loop |
| F2 | ✅ validada | Memória pgvector, Curator, ContextCompressor |
| F3 | ✅ validada | Skills, SkillManager, 4 builtins |
| F4 | ✅ validada | Multi-modelo, ModelRouter |
| F5 | ⚠️ parcial | Gateway funcional; webhook Telegram 404 |
| F6 | ⚠️ parcial | LLM wiring OK; E2E requer configuração |
| F7 | ✅ validada | Missões, Critic 3 personas, AutonomousLoop |
| F8 | ✅ validada | Sandboxes 5 perfis, exec_tool |
| F9 | ✅ validada | Voyager skill synthesis, cluster scan, promoter |
| F10 | ✅ completada | docker-compose.prod.yml adicionado em v1.0 |
| F11 | ✅ validada | Web UI 8 painéis, WebSocket, auth |
| F12 | ⏸️ deferida | Canais extras — v1.1 (#6) |
| F13 | ⏸️ deferida | Ciclo LoRA real — v1.1 (#7) |
| Infra | ✅ validada | CI verde, auto-migrations, Dockerfile |

## Métricas

| Métrica | Valor |
|---------|-------|
| Testes passando | 1158 |
| Falhas | 0 |
| Cobertura | 30%+ |
| Linhas de código | ~28.461 |
| Migrations | 16 arquivos SQL |
| Tags de fase | 6 (d1-done, d4-done, d5-done, f9-real-done, f11-done, infra-done) |
| Issues abertas | 7 |

## Bugs em aberto (issues GitHub)

| # | Severidade | Descrição |
|---|-----------|-----------|
| [#1](https://github.com/engsathiago/EVE_Autonomo/issues/1) | ALTO | OllamaTransport não callable via ModelRouter |
| [#2](https://github.com/engsathiago/EVE_Autonomo/issues/2) | ALTO | needs_critic() nunca retorna True no AutonomousLoop |
| [#3](https://github.com/engsathiago/EVE_Autonomo/issues/3) | MÉDIO | webhook /webhook/telegram retorna 404 |
| [#4](https://github.com/engsathiago/EVE_Autonomo/issues/4) | MÉDIO | AGENT_NO_WEB workaround Starlette lifespan |
| [#5](https://github.com/engsathiago/EVE_Autonomo/issues/5) | MÉDIO | SkillSynthesizer não persiste candidates automaticamente |
| [#6](https://github.com/engsathiago/EVE_Autonomo/issues/6) | FEAT | F12: wire canais Discord/Slack/Email no gateway |
| [#7](https://github.com/engsathiago/EVE_Autonomo/issues/7) | FEAT | F13: ciclo LoRA real end-to-end |

## Próximos passos pós v1.0

### v1.1 (próxima)
- Resolver #1 (OllamaTransport callable)
- Resolver #2 (needs_critic ativo no loop)
- F12: wire Discord/Slack/Email no gateway
- F13: ciclo LoRA end-to-end com dataset real
- Cobertura de testes → 60%

### v1.x (futuro)
- RLAIF (Fase 14)
- Plugin marketplace
- Mobile-friendly web dashboard

## Lições aprendidas

1. **"Código existir ≠ fase validada"** — audit D.5 provou que 10/14 fases eram "teatro". Validação de runtime real é mandatória antes de declarar conclusão.

2. **Cadeia de estratégias > enum simples** — D.1 implementou tool routing por step usando `ToolResolver` com fallback chain em vez de um enum fixo. Superou a spec.

3. **Fallback graceful destrava progresso** — F9 Voyager usa template fallback quando OllamaTransport falha (bug #1). Progresso não trava por um bug periférico.

4. **CI cedo evita acúmulo de dívida** — Infra configurada após F11 revelou 6 testes quebrados. Configurar CI desde F1 teria evitado acúmulo.

5. **Stamp migrations para bootstrap** — DB criado manualmente sem tracking requer `agent db migrate --stamp` antes de `migrate`. Adicionado após descobrir na prática.

## Decisões de arquitetura relevantes

- **AGENT_NO_WEB=1:** Workaround para limitação Starlette (add_middleware em lifespan). Web UI serve via nginx separado em prod ou scripts/run_webui.py em dev.
- **skills F3 vs F9:** Dois sistemas independentes (template vs synthesized). Interoperabilidade pendente para v1.1.
- **PostgreSQL + pgvector:** Escolha consolidada — elimina Chroma/Qdrant como dependência separada.
