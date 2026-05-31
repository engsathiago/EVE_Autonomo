# FASE F11 — Web UI Dashboard

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-f9-real-done`.

## Objetivo único

Dashboard web estilo terminal (referência: gaahzx/jarvis, mas mais rico), conectado ao gateway Node existente. **Read-mostly** — exibe estado, permite chat e aprovações; tudo destrutivo passa por confirmação dupla.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **Stack fixa:** React + TypeScript + Tailwind + Vite. Sem Next.js (overkill).
3. **Dados via REST + WebSocket** no gateway Node existente. NÃO adiciona dependência nova.
4. **Sem autenticação complexa nesta fase.** HTTP basic auth via env vars, suficiente pra single-user.
5. **Tema escuro terminal-style.** Fonte mono. Verde/âmbar em fundo preto.

## Painéis obrigatórios

1. **Chat ao vivo** — input + histórico (poll ou WS no `channel_messages`)
2. **Missions** — lista, status, steps, último step rodado
3. **Skills** — todas (manuais + auto), com contador de invocações, filtro `auto_generated`
4. **Memória semântica** — busca por embedding (input → top 5 resultados)
5. **Mission traces** — clica numa mission, vê todos os `tool_executions` em timeline
6. **Critic queue** — `critic_evaluations` recentes + verdict + persona breakdown
7. **Subagent health** — runs ativos, tempo médio, taxa de sucesso
8. **Pending approvals** — lista de `pending_approvals` com botões Approve/Reject
9. **Evolution metrics** — gráfico de skills auto-geradas por semana, missões completas, taxa de `failed_no_execution`

## Passos

### 1. Auditar UI existente

```bash
cd ~/Desktop/agent
ls -la web/ ui/ frontend/ dashboard/ 2>/dev/null
```

Se existe pasta com Vite/React funcional → branch a partir dela. Se existe mas quebrada → backup em `web_legacy_$(date +%s)/` e começa do zero. Se nada existe → cria do zero.

Decisão documentada em `F11_DECISAO_BASE.md`.

### 2. Scaffold (se from scratch)

```bash
cd ~/Desktop/agent
npm create vite@latest web -- --template react-ts
cd web
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install @tanstack/react-query axios date-fns recharts lucide-react
```

Configura Tailwind com tema terminal:

```js
// tailwind.config.js
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        panel: "#111111",
        border: "#2a2a2a",
        accent: "#00ff88",
        warn: "#ffb000",
        danger: "#ff4444",
        muted: "#888888",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
};
```

### 3. Endpoints REST no gateway

Adiciona em `gateway/src/routes/dashboard.ts`:

```typescript
// GET /api/dashboard/missions
// GET /api/dashboard/missions/:id/trace
// GET /api/dashboard/skills?auto=true|false
// GET /api/dashboard/critic?limit=20
// GET /api/dashboard/subagents/health
// GET /api/dashboard/approvals/pending
// POST /api/dashboard/approvals/:id/resolve  (body: {decision:'approve'|'reject'})
// POST /api/dashboard/memory/search  (body: {query:string, top_k:int})
// GET /api/dashboard/metrics/evolution?window=7d|30d
```

Cada endpoint faz query no Postgres compartilhado e retorna JSON. Sem cache (read-time só).

### 4. WebSocket pra updates

`gateway/src/ws/dashboard.ts` — assina Redis pub/sub em canais:
- `missions:updated`
- `tool_executions:new`
- `approvals:new`
- `critic:new`

Broadcasts pro frontend conectado.

### 5. Componentes React

Estrutura mínima em `web/src/`:

```
src/
  components/
    Panel.tsx          # wrapper estilo terminal (border + título)
    MissionsList.tsx
    MissionTrace.tsx
    SkillsTable.tsx
    MemorySearch.tsx
    CriticQueue.tsx
    SubagentHealth.tsx
    ApprovalsList.tsx
    EvolutionChart.tsx
    ChatLive.tsx
  hooks/
    useApi.ts          # wrapper react-query
    useWebSocket.ts
  layouts/
    DashboardLayout.tsx  # grid 3 colunas
  App.tsx
  main.tsx
```

Layout: grid 3 colunas em desktop, stack em mobile. Coluna esquerda = navegação + métricas. Centro = painel ativo. Direita = chat sempre visível.

### 6. Aprovação dupla pra destrutivo

Botão "Reject approval" → modal com input "digite REJEITAR pra confirmar". Idem pra qualquer ação que muda estado.

### 7. Build + deploy local

```bash
cd web
npm run build
```

Adiciona no `docker-compose.yml`:
```yaml
web:
  image: nginx:alpine
  ports: ["8080:80"]
  volumes:
    - ./web/dist:/usr/share/nginx/html:ro
    - ./web/nginx.conf:/etc/nginx/conf.d/default.conf:ro
  depends_on: [gateway]
```

Cria `web/nginx.conf` com proxy `/api/*` e `/ws` pro gateway.

### 8. Testes mínimos

`web/src/__tests__/`:
- Renderiza `Panel` com título
- `MissionsList` faz fetch e exibe rows
- `ApprovalsList` botão "Reject" abre modal de confirmação

```bash
cd web && npm test
```

### 9. Smoke E2E manual (mas obrigatório)

```bash
docker compose up -d
open http://localhost:8080
```

Checklist no chat ou em `RELATORIO_F11.md`:
- [ ] Dashboard carrega
- [ ] Lista de missions populada
- [ ] Chat envia e recebe mensagem
- [ ] Memory search retorna resultados
- [ ] Approval pendente aparece e é resolvível
- [ ] Critic queue mostra últimas decisões
- [ ] Subagent health atualiza via WS quando novo run inicia

### 10. Commit + tag + push

```bash
cd ~/Desktop/agent
git add -A
git commit -m "feat(f11): dashboard web terminal-style

- Vite + React + TS + Tailwind, sem Next
- 9 painéis: chat, missions, skills, memory, traces, critic, subagents, approvals, metrics
- REST + WS via gateway Node existente
- Aprovação dupla em ações destrutivas
- Tema terminal escuro

Resolve: F11 do roadmap"

git tag fase-f11-done
git push origin main --tags
```

### 11. Relatório

`RELATORIO_F11.md` com checklist acima + screenshot opcional + bugs encontrados.

## Critério de aceite

- `http://localhost:8080` serve dashboard sem erro
- 9 painéis funcionais (mesmo que minimalistas)
- 1 aprovação resolvida via UI gera evento em `pending_approvals.resolved_at`
- WS atualiza em tempo real (testar com 2 abas)
- Tag `fase-f11-done`

## Se faltar tempo de sessão

Prioriza nesta ordem (desce de baixo pra cima se cortar):
1. Missions + Trace
2. Approvals (segurança)
3. Chat
4. Skills + Memory
5. Critic queue
6. Subagent health
7. Evolution metrics (corta se faltar)

Painéis não terminados ficam como stub com texto "WIP — fase F11.1".

## NÃO faça

- Não adiciona Next.js, tRPC, Prisma, ou outra layer.
- Não tenta auth complexa (OAuth, JWT) — basic auth basta nessa fase.
- Não pergunta nada.
