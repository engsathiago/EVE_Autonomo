# Plano de Limpeza — gerado em 2026-05-30

Auditoria realizada em `feature/d6-skills-perms` antes do merge para `main`.
Objetivo: remover artefatos de sessões anteriores ("Hermes debris"), atualizar
`.gitignore` e documentar issues conhecidos sem consertar código de produção.

---

## A. DELETE — lixo rastreado pelo git

| Caminho | Motivo |
|---------|--------|
| `cli/pyproject.toml.bak` | Arquivo de backup criado por edição automática em sessão anterior; pyproject.toml original não foi corrompido |
| `cli/src/cli/skills.py.bak` | Backup do módulo de skills gerado durante refactoring manual; versão real está em `skills.py` |

---

## B. MOVER para `docs/archive/hermes-debris/`

| Caminho | Motivo |
|---------|--------|
| `docker-compose.d5.yml` | Compose temporário de validação D5 com senha hardcoded (`qualquercoisa123`); artefato de experimento, não é o compose de produção |

---

## C. ADD ao `.gitignore`

| Padrão | Motivo |
|--------|--------|
| `BUG_PATTERN_MAP.md` | Relatório de auditoria gerado automaticamente; outros relatórios similares já estão no .gitignore (AUDIT_REPORT.md, LINT_ISSUES.md, etc.) mas este ficou de fora |

---

## D. KNOWN ISSUES — documentados, NÃO consertados aqui

| Arquivo / Localização | Problema | Ref |
|-----------------------|----------|-----|
| `docker-compose.d5.yml:6` | Senha `qualquercoisa123` hardcoded no DSN de validação D5 (arquivo será movido para archive) | — |
| `core/src/agent/core.py:303` (`_execute_tools`) | Critic não está conectado ao mission flow em runtime; as 9 `critic_evaluations` existentes no DB são órfãs (sem `mission_id` ou `task_id`) | D.4 |
| `core/src/agent/subagents/pool.py` (timeout) | Timeout fixo por tier — não adaptativo por modelo; qwen3:30b local ultrapassa 60s e resulta em prosa por timeout | D.2 |
| `core/src/agent/models/router.py:271` (record) | FK violation em `model_invocations` quando session_id não tem conversa parent (smoke tests e invocações de cron sem contexto) | D.3 |
| `core/src/agent/memory/store.py` (Curator) | Curator salva memórias sem deduplicação efetiva: 12 das 15 entradas no DB são variações da mesma frase | EXECUTION_AUDIT §2 |
| `core/src/agent/skills/creator.py` (SkillCreator) | SkillCreator nunca foi exercitado em runtime real — criação dinâmica de skills a partir de sessão é TEÓRICA | EXECUTION_AUDIT §2 |
| `core/src/agent/subagents/pool.py` (`tools_used`) | Campo `tools_used` em `subagent_runs` registra tools **disponíveis**, não **executadas** — schema é enganoso | EXECUTION_AUDIT §5 |

---

## E. MOVER para `docs/audit/`

| Caminho atual | Destino | Motivo |
|--------------|---------|--------|
| `EXECUTION_AUDIT.md` | `docs/audit/EXECUTION_AUDIT.md` | Documento de auditoria pertence à pasta de audit, não à raiz |
| `FASE_D_BACKLOG.md` | `docs/phases/FASE_D_BACKLOG.md` | Backlog de fases pertence à pasta de phases |
