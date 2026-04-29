# Como usar o Claude Code nesse projeto sem queimar limite

> Esse arquivo é seu manual operacional. Releia antes de cada sessão grande.

## Setup inicial (uma vez só)

1. Instalar Claude Code:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. Na pasta do projeto:
   ```bash
   cd agent
   claude
   ```

3. Confirme que ele leu o `CLAUDE.md`:
   ```
   /context
   ```
   Deve listar `CLAUDE.md` entre os arquivos carregados.

## Fluxo padrão de uma fase

### 1. Abrir nova sessão
```bash
cd agent
claude
```

Sempre comece nova sessão por fase. Não reaproveite contexto velho.

### 2. Carregar o spec
```
Vou trabalhar na Fase X. Leia docs/phases/phase-X-spec.md e me dê
um plano detalhado antes de codar. Não escreva código ainda.
```

### 3. Revisar o plano
Ele vai responder com lista de arquivos, ordem, decisões. Você:
- Aprova: "Pode executar."
- Ajusta: "Mude X pra Y, então execute."
- Pergunta: "Por que escolheu A em vez de B?"

### 4. Executar
Deixe ele trabalhar. Não interrompa a menos que veja algo errado.

### 5. Validar
No fim, sempre rode os testes/build conforme o critério de aceite.

### 6. Commit
```bash
git add .
git commit -m "feat: fase X — descrição curta"
```

### 7. Atualizar o CLAUDE.md
Marque o checkbox da fase concluída.

### 8. Encerrar a sessão
Não fique conversando depois que a fase terminou. Feche e abra de novo
pra próxima fase. Cada sessão limpa = menos tokens consumidos.

## Comandos úteis do Claude Code

- `/clear` — limpa contexto da sessão atual (use entre sub-tarefas grandes)
- `/compact` — comprime histórico (use quando ficar longo)
- `/context` — mostra arquivos carregados
- `/cost` — mostra quanto a sessão custou
- `/plan` — entra em plan mode (não executa, só planeja)
- `@nome-do-agent` — invoca subagente especializado

## Atalhos pra economizar muito

### Use plan mode pra mudanças grandes
```
/plan implemente o ContextCompressor seguindo docs/specs/memory.md
```
Ele só planeja, não executa. Você aprova, aí ele executa.

### Use subagentes pra trabalho repetitivo
```
@core-builder adicione uma tool de leitura de PDF usando pypdf
```
O subagente trabalha em contexto isolado e retorna só o resumo. **Custa
menos** que fazer no chat principal.

### Use skills pra padrões recorrentes
```
Use a skill add-tool pra criar uma tool de busca no Tavily.
```

### Limite escopo explicitamente
✅ "Implemente apenas core/src/agent/memory/store.py. Não toque em outros
arquivos."

❌ "Implemente a memória."

A primeira gasta 10x menos.

### Use Haiku quando possível
Pra tarefas simples (escrever testes, refatorar arquivos pequenos), peça:
```
Use Haiku pra essa tarefa.
```
Ou no `.claude/agents/test-writer.md`, já especifica `model: haiku`.

## Quando trocar de modelo

| Tarefa | Modelo |
|---|---|
| Planejamento de fase, decisões arquiteturais | Opus |
| Implementação normal (90% do tempo) | Sonnet |
| Testes, refactors simples, docs | Haiku |
| Debugging de bug feio | Opus |

## Sinais de que você tá gastando demais

1. **Arquivo com 500+ linhas:** divida em módulos antes de pedir mudança.
2. **Sessão > 2 horas:** dê `/compact` ou abra nova.
3. **Mesmo erro 3x seguidas:** páre, abra nova sessão, dê mais contexto.
4. **Ele "explorando" arquivos sem rumo:** seu prompt não foi específico
   o suficiente — refine.

## Anti-padrões

❌ **"Continue de onde parou"** — não tem como, contexto é volátil. Sempre
dê o contexto completo do que precisa.

❌ **"Implemente tudo da Fase X"** sem ler o spec — mesmo com CLAUDE.md, ele
precisa do spec da fase.

❌ **Misturar duas fases na mesma sessão** — cada fase = sessão própria.

❌ **Não validar entre fases** — se a Fase 1 tem bug, a Fase 2 nasce torta.

❌ **Não commitar entre fases** — se você quiser voltar, não consegue.

## Estimativa de custo

Pra uma fase média (Sonnet, ~3 horas de trabalho dele):
- ~200k tokens de input
- ~50k tokens de output
- Custo: aproximadamente $1-2 USD

Projeto inteiro (12 fases): **$15-30 USD**.

Plano Pro do Claude inclui Claude Code com limites generosos. Plano Max
remove a maioria das fricções. Pra esse projeto, **Pro deve dar conta**.

## Quando pedir ajuda em vez de Claude Code

Use o chat normal do Claude (claude.ai) quando:
- Estiver decidindo arquitetura grande
- Precisar do plano de uma fase nova
- Quiser revisar código sem editar
- Estiver debuggando algo conceitual

Use Claude Code quando:
- For escrever/editar arquivos
- For rodar comandos
- For refatorar
- For escrever testes
