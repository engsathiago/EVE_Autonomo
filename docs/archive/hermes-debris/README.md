# Arquivo — Detritos de Sessões Anteriores

Esta pasta preserva artefatos gerados por sessões automatizadas que,
em algum momento, editaram o repositório de forma não estruturada.
Os arquivos aqui têm **valor histórico** (mostram o que aconteceu),
mas não devem ser usados em produção.

---

## Conteúdo

### `docker-compose.d5.yml`

**Origem:** sessão de validação da melhoria D.5 (re-validação de fases TEÓRICAS).

**O que é:** compose temporário criado para isolar o ambiente de teste do D.5,
com banco de dados `agent_d5_validation` separado do banco de produção.

**Por que não está na raiz:** contém senha de banco hardcoded (`qualquercoisa123`),
que embora seja de teste e sem valor em produção, não deve ficar visível na raiz.
O compose de produção correto é `docker-compose.yml` na raiz do repositório.

**Não use este arquivo.** Use `docker-compose.yml`.

---

*Movido para cá em 2026-05-30 durante cleanup pós-auditoria.*
*Ver `CLEANUP_PLAN.md` na raiz para o plano completo.*
