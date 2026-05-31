# FASE CLEANUP — VPS limpa, docs finais, release v1.0.0

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-f13-real-done` ou `fase-f13-skipped`.

## Objetivo único

Fechar o projeto. Limpar VPS do desastre do Hermes, deploy limpo, varrer todos os `BUGS_ENCONTRADOS_*.md`, fechar issues, gerar docs finais, criar release `v1.0.0`.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **VPS antiga (72.61.44.253):** snapshot antes de qualquer mudança. Se snapshot impossível, documenta em `CLEANUP_RISCO.md` e segue mesmo assim.
3. **Bug `BUGS_ENCONTRADOS_*.md` de fases anteriores:** triagem severa — bug crítico conserta agora; cosmético vira issue no GitHub.
4. **Release v1.0.0 só sai se TODA a CI estiver verde e smoke E2E passar no deploy.**

## Passos

### 1. Triagem dos bugs acumulados

```bash
cd ~/Desktop/agent
ls BUGS_ENCONTRADOS_*.md DECISOES_*.md 2>/dev/null
cat BUGS_ENCONTRADOS_*.md > /tmp/all_bugs.md
```

Classifica cada bug:
- **CRÍTICO** (impede uso, segurança, perda de dados) → conserta agora
- **ALTO** (degrada experiência, fácil de bater) → cria issue GitHub `priority/high`
- **MÉDIO/BAIXO** → issue `backlog`

Cria `RELATORIO_CLEANUP_BUGS.md` com a classificação.

Pra cada CRÍTICO:
1. Branch `fix/bug-XXX`
2. Implementa fix
3. Teste de regressão
4. Merge em main
5. Marca resolvido no `BUGS_ENCONTRADOS_*.md` original

### 2. Limpar VPS antiga

```bash
ssh root@72.61.44.253 'docker ps -a; ls -la /opt /root | head -30; cat /etc/cron.d/* 2>/dev/null'
```

Se VPS tem qualquer coisa do Hermes (sandbox off, keys hardcoded, cron rodando coisa antiga):

```bash
ssh root@72.61.44.253 'systemctl stop docker'
# snapshot via provider antes de seguir
```

Decisão: VPS reaproveitável? Se sim, passo 3. Se não, provisiona nova VPS.

### 3. Deploy limpo

Na VPS (nova ou limpa):

```bash
# pre-reqs
apt update && apt install -y docker.io docker-compose-plugin git
git clone https://github.com/engsathiago/EVE_Autonomo.git /opt/eve
cd /opt/eve

# secrets
cp .env.example .env
nano .env   # preenche ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, OLLAMA_CLOUD_KEY, POSTGRES_PASSWORD
chmod 600 .env

# pull images
docker compose -f docker-compose.prod.yml pull

# boot (aplica migrations automaticamente via script da Fase Infra)
docker compose -f docker-compose.prod.yml up -d

# logs
docker compose -f docker-compose.prod.yml logs -f --tail=50
```

Aguarda boot completo.

### 4. Smoke E2E em produção

```bash
# health
curl -f http://localhost:3000/health
curl -f http://localhost:8080/

# missão de teste
curl -X POST http://localhost:3000/api/missions \
  -H 'Content-Type: application/json' \
  -d '{"tier":"INSTANT","goal":"liste arquivos em /tmp"}'

# checa DB
docker compose -f docker-compose.prod.yml exec postgres psql -U agent -d agent -c \
  "SELECT count(*) FROM mission_steps WHERE created_at > NOW() - INTERVAL '5 minutes';"
```

Tudo verde antes de seguir.

### 5. Atualizar docs

#### `README.md` (raiz)

Reescreve com seções:
- Visão geral curta (3 linhas)
- Arquitetura resumida + diagrama ASCII
- Quick start local (`docker compose up`)
- Quick start produção (link pra DEPLOY.md)
- Estado do projeto (badges CI, cobertura, versão)
- Roadmap pós v1.0 (curto)
- Licença

#### `CLAUDE.md`

Atualiza checklist de fases — todas marcadas com status real (validada / parcial / skipped).

#### `docs/ARCHITECTURE.md`

Reescreve com o estado pós-D.1/D.4. Diagrama de componentes (ASCII ou Mermaid). Pontos de extensão.

#### `docs/DEPLOY.md`

Passo a passo de deploy VPS do passo 3 acima, com troubleshooting comum.

#### `docs/SECURITY.md`

Lista de garantias atuais (sandbox, Critic gating, irreversibilidade, approval flow) e limites conhecidos.

#### `CHANGELOG.md`

Histórico de tags com 1 linha cada:
```
## v1.0.0 — 2026-XX-XX
- F0–F13 todas validadas em runtime
- D.1 tool routing, D.4 Critic integration, D.5 re-validação
- Web UI completa, CI+migrations automáticas
- LoRA ciclo 1: [aceito/rejeitado/skipped]
```

### 6. Issues do GitHub

Pra cada bug ALTO/MÉDIO do passo 1, abre issue via CLI ou web:

```bash
gh issue create --title "fix: <descrição>" \
  --label "priority/high" \
  --body "Detectado em FASE X. Reprodução: ..."
```

### 7. Release v1.0.0

Só se TUDO verde:

```bash
# verificar
git status   # limpo
gh run list --limit 1   # CI passou

# tag
git tag -a v1.0.0 -m "EVE_Autonomo v1.0.0

Primeira release estável.

Fases entregues e validadas em runtime:
F0 Fundação · F1 Core · F2 Memória · F3 Skills · F4 Multi-modelo
F5 Gateway+Telegram · F6 Cron+Subagentes · F7 Missões+Conclave
F8 Sandbox · F9 Voyager skills · F10 Deploy VPS · F11 Web UI
F12 Canais · F13 LoRA: [aceito/skipped]

Fixes estruturais: D.1 tool routing, D.4 Critic, D.5 re-validação."

git push origin v1.0.0

gh release create v1.0.0 \
  --title "v1.0.0 — EVE_Autonomo estável" \
  --notes-file CHANGELOG.md \
  --latest
```

### 8. Relatório final

`RELATORIO_FINAL.md`:
```markdown
# Projeto EVE_Autonomo — Relatório Final

## Status: 100% concluído (ou X% se algum bloqueio)

## Fases entregues
[checklist com tags]

## Métricas finais
- Linhas de código: ___
- Testes: ___ verdes
- Cobertura: __%
- Skills auto-geradas: ___
- Missions executadas em prod: ___

## Bugs em aberto
[lista do RELATORIO_CLEANUP_BUGS.md]

## Lições aprendidas
- Decisões boas: ...
- Decisões ruins: ...
- Anti-padrões evitados: Hermes, EVE-Agent TS, gaahzx vocabulary

## Próximos passos pós v1.0
- F14+ RLAIF (experimental)
- Cobertura → 80%
- Bugs ALTO pendentes
```

### 9. Commit final + push

```bash
git add -A
git commit -m "chore(cleanup): release v1.0.0 — projeto fechado

- Docs reescritas (README, ARCHITECTURE, DEPLOY, SECURITY)
- VPS limpa e deploy validado
- CHANGELOG.md completo
- Bugs críticos resolvidos, demais viraram issues
- Release v1.0.0 criada no GitHub"
git push origin main
```

## Critério de aceite

- VPS rodando saudável por pelo menos 1h sem crash
- Smoke E2E em prod retorna sucesso
- CI verde no commit final
- Release `v1.0.0` publicada no GitHub
- `RELATORIO_FINAL.md` completo
- Todos os `BUGS_ENCONTRADOS_*.md` triados (consertados ou viraram issue)

## Se não consegue 100%

Se algum item travou (ex: VPS antiga inacessível), documenta em `RELATORIO_FINAL.md` o que ficou faltando + plano explícito, e cria release `v1.0.0-rc1` ao invés de `v1.0.0`. Não bloqueia.

## NÃO faça

- Não cria release sem CI verde.
- Não deleta VPS antiga sem snapshot.
- Não pergunta nada.
