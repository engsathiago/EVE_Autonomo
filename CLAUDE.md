# Agente Autônomo — Instruções Mestre

> Este arquivo é lido automaticamente pelo Claude Code em toda sessão.
> Ele contém o contexto global do projeto. Atualize quando algo mudar.

## Visão geral

Construindo um agente autônomo inspirado em **Hermes Agent** (Nous Research) e
**OpenClaw** (Peter Steinberger). Pega o melhor dos dois:

- **Do Hermes:** loop autônomo, memória curada, skills auto-criadas, cron,
  subagentes, multi-provider, ContextCompressor.
- **Do OpenClaw:** gateway central, config via SOUL.md, multi-canal, plugins
  drop-in, MCP nativo, approvals.

## Stack

- **Core:** Python 3.11+, FastAPI, asyncio, asyncpg, ChromaDB-compatible via pgvector
- **Gateway:** Node 20+, TypeScript, Fastify, telegraf/discord.js/baileys
- **DB:** PostgreSQL 16 (com pgvector)
- **Bus:** Redis 7 (pubsub + queue)
- **Web UI:** HTML + vanilla JS (sem build, sem framework)
- **Deploy:** Docker Compose em VPS (DigitalOcean/Hetzner)

## Convenções

### Python
- async/await em todo IO
- Type hints sempre, validação com pydantic v2
- Imports absolutos (`from agent.tools.registry import ...`)
- Erros encapsulados, nunca `except: pass`
- Logging estruturado via `agent.observability.logger`
- Testes com pytest + pytest-asyncio

### TypeScript
- Strict mode no tsconfig
- ESM (`"type": "module"`)
- Zod pra validação
- Pino pra logs
- Testes com vitest

### Geral
- Commits conventional: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- Cada arquivo novo precisa de teste correspondente
- Nada de comentários óbvios; só explicar o "porquê", não o "o quê"

## Estado atual do projeto

> ATUALIZE ESTA SEÇÃO APÓS CADA FASE

- [x] Fase 0: Fundação
- [x] Fase 1: Core mínimo
- [x] Fase 2: Memória — MemoryStore (pgvector + FTS multilingual, busca híbrida via RRF), Curator (Haiku 4.5) decidindo o que persistir, ContextCompressor para histórico longo, tools `salvar_memoria` e `ler_memoria`, persistência cross-sessão validada (E2E OpenClaw passou)
- [ ] Fase 3: Skills
- [ ] Fase 4: Multi-modelo
- [ ] Fase 5: Gateway + Telegram
- [ ] Fase 6: Discord + WhatsApp + Slack
- [ ] Fase 7: Web UI
- [ ] Fase 8: Cron + Subagentes
- [ ] Fase 9: Sandboxes
- [ ] Fase 10: Plugins + MCP
- [ ] Fase 11: Deploy

## Diretrizes para o Claude Code

1. **Sempre planejar antes de codar.** Para qualquer mudança em mais de 2
   arquivos, gere primeiro um plano e espere aprovação.

2. **Use as skills locais.** Sempre que possível, use as skills em
   `.claude/skills/`. Elas têm o padrão correto.

3. **Escopo restrito.** Mexa apenas nos arquivos solicitados. Se precisar
   tocar em outros, pergunte.

4. **Testes não são opcionais.** Todo arquivo novo precisa de teste.

5. **Não invente APIs externas.** Se uma biblioteca tem comportamento
   incerto, busque a documentação real ou pergunte.

6. **Mantenha o agente funcional.** Cada fase deve deixar o sistema rodando.
   Nunca faça commits que quebrem o build.

7. **Atualize CLAUDE.md.** Quando concluir uma fase, marque o checkbox e
   atualize a seção de estado.

## Estrutura do projeto

```
agent/
├── core/          # Python (AIAgent, memória, skills, tools)
├── gateway/       # Node (canais de mensagem)
├── webui/         # HTML/JS estático
├── cli/           # Python CLI
├── config/        # SOUL.md, AGENTS.md, TOOLS.md, config.yaml
├── deploy/        # Scripts e configs de deploy
├── docs/
│   ├── architecture.md
│   ├── phases/    # Specs de cada fase
│   └── decisions/ # ADRs (Architecture Decision Records)
└── .claude/
    ├── skills/    # Padrões reutilizáveis
    └── agents/    # Subagentes especialistas
```

## Comunicação Python ↔ Node

- **Mensagens em tempo real:** Redis pubsub
  - Canal `agent:in` — Node publica mensagens recebidas dos canais
  - Canal `agent:out:{channel_id}` — Python publica respostas
  - Canal `agent:stream:{request_id}` — Python publica chunks de streaming
- **Comandos:** HTTP REST entre os serviços
  - Python expõe `/api/chat`, `/api/jobs`, `/api/skills`
  - Node expõe `/api/send`, `/api/health`
- **Streaming:** Server-Sent Events do Python pro Web UI direto

## Variáveis de ambiente

Veja `.env.example`. Nunca commite `.env` real.

## Modelos recomendados

- **Planner/Reasoner do agente:** `claude-haiku-4-5` (rápido, tool use confiável)
- **Reflector/Critic:** `claude-sonnet-4-6` (raciocínio profundo)
- **Memória/Sumarização:** `qwen2.5:7b-instruct` via Ollama (local, grátis)
- **Embeddings:** `paraphrase-multilingual-MiniLM-L12-v2` (PT+EN)

## O que NÃO fazer

- ❌ Não use `print()` — use o logger.
- ❌ Não bloqueie a event loop com chamadas síncronas pesadas.
- ❌ Não escreva em arquivos sem `pathlib`.
- ❌ Não hardcode credenciais; use env vars.
- ❌ Não crie bibliotecas Python sem `pyproject.toml`.
- ❌ Não use `any` em TypeScript sem motivo justificado por comentário.
