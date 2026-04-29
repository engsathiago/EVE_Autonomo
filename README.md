# Kit Inicial — Agente Autônomo Híbrido

Esse é o ponto de partida do seu projeto. Contém:

```
agent_kit/
├── CLAUDE.md                       ← cole na raiz do seu projeto
├── docs/
│   ├── architecture.md             ← referência arquitetural
│   ├── claude-code-guide.md        ← manual operacional do Claude Code
│   └── phases/
│       └── phase-0-spec.md         ← spec da fase 0 (cole no Claude Code)
└── README.md                       ← esse arquivo
```

## Como começar (passo a passo)

### 1. Crie o repo
```bash
mkdir agent && cd agent
git init
```

### 2. Cole os arquivos do kit
Copie tudo que tá nesse zip pra raiz do `agent/`:
```
agent/
├── CLAUDE.md
└── docs/
    ├── architecture.md
    ├── claude-code-guide.md
    └── phases/
        └── phase-0-spec.md
```

### 3. Primeiro commit
```bash
git add .
git commit -m "chore: kit inicial"
```

### 4. Instale o Claude Code
```bash
npm install -g @anthropic-ai/claude-code
```

### 5. Abra o Claude Code na pasta
```bash
claude
```

### 6. Inicie a Fase 0
Cole exatamente isso na primeira mensagem:

> Leia `CLAUDE.md` e `docs/phases/phase-0-spec.md`. Antes de codar, me dê o plano detalhado pra Fase 0. Não escreva código ainda.

### 7. Aprove o plano e deixe executar

### 8. Valide
```bash
docker compose up --build -d
curl http://localhost:8000/health
curl http://localhost:8001/health
```

### 9. Commit
```bash
git add .
git commit -m "feat: fase 0 — fundação"
```

### 10. Volte aqui pra eu te dar o spec da Fase 1

## Roadmap das fases

| # | Fase | Status |
|---|---|---|
| 0 | Fundação | Spec pronto |
| 1 | Core mínimo (AIAgent + Anthropic + 3 tools + CLI) | A fazer |
| 2 | Memória (PostgreSQL + pgvector + curator) | A fazer |
| 3 | Skills (manager + creator automático) | A fazer |
| 4 | Multi-modelo (OpenAI + OpenRouter + Ollama) | A fazer |
| 5 | Gateway Node + Telegram | A fazer |
| 6 | Discord + WhatsApp + Slack | A fazer |
| 7 | Web UI (vanilla JS + SSE) | A fazer |
| 8 | Cron + Subagentes | A fazer |
| 9 | Sandboxes (Docker + SSH) | A fazer |
| 10 | Plugins + MCP | A fazer |
| 11 | Deploy (DO/Hetzner) | A fazer |

## Importante

**Leia `docs/claude-code-guide.md` antes de começar.** É o que vai te
salvar de queimar limite à toa.

## Quando terminar a Fase 0

Volta aqui no chat e me fala:
> "Fase 0 concluída. Pode me passar o spec da Fase 1?"

Eu te entrego o `phase-1-spec.md` na hora. Mesma coisa pra cada fase
seguinte.
