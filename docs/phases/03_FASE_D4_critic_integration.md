# FASE D.4 — Critic Ligado ao Mission Flow

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Pré-requisito: `fase-d5-done`.

## Objetivo único

Ligar o Conclave Critic (3 personas) ao fluxo de execução de missões via hooks em `AIAgent._execute_tools()`. Toda ação irreversível passa pelo Critic ANTES de executar; veredito `REJECT` bloqueia, `ESCALATE` cria approval pendente no Telegram, `APPROVE` libera.

## Regras duras

1. **NÃO pergunta.** Decide e executa.
2. **NÃO usa `sed`/heredoc** pra Python.
3. **Compatibilidade pra trás:** se nenhum tool é marcado como irreversível, comportamento atual permanece.
4. **Critic só roda em decisões irreversíveis.** Não gateia todas as ações (latência explode).
5. **Timeout do Critic: 30s.** Se estourar, decisão default é `ESCALATE`.

## Passos

### 1. Classificar tools como irreversíveis

Edita `core/src/agent/tools/registry.py` (ou onde tools são registradas). Adiciona flag `irreversible: bool` na metadata de cada tool:

| Tool | Irreversível? |
|---|---|
| read_file | não |
| list_dir | não |
| web_search | não |
| web_fetch | não |
| write_file | **sim** se path fora de `/tmp` ou `sandbox/` |
| shell | **sim** se contém `rm`, `mv`, `git push`, `docker`, `sudo`, `curl -X POST/DELETE/PUT` |
| send_telegram | **sim** (manda mensagem pro usuário) |

Cria helper `core/src/agent/critic/irreversibility.py`:

```python
"""Decide se uma chamada de tool é irreversível baseado em args."""
import re

IRREVERSIBLE_SHELL_PATTERNS = [
    r"\brm\b", r"\bmv\b", r"\bgit\s+push\b", r"\bdocker\b",
    r"\bsudo\b", r"curl\s+-X\s+(POST|DELETE|PUT)", r">\s*\S+",
]

def is_irreversible(tool_name: str, args: dict) -> tuple[bool, str]:
    """Retorna (é_irreversível, motivo)."""
    if tool_name in ("read_file", "list_dir", "web_search", "web_fetch"):
        return False, ""
    if tool_name == "write_file":
        path = args.get("path", "")
        if path.startswith("/tmp") or "sandbox/" in path:
            return False, ""
        return True, f"write_file fora de sandbox: {path}"
    if tool_name == "shell":
        cmd = args.get("command", "")
        for pat in IRREVERSIBLE_SHELL_PATTERNS:
            if re.search(pat, cmd):
                return True, f"shell match {pat}: {cmd[:80]}"
        return False, ""
    if tool_name == "send_telegram":
        return True, "envio externo de mensagem"
    # default: tools desconhecidas tratam como irreversíveis pra ser seguro
    return True, f"tool desconhecida: {tool_name}"
```

### 2. Hook no `AIAgent._execute_tools()`

Localiza `core/src/agent/ai_agent.py` (ou equivalente). Antes de executar cada tool, chama:

```python
from agent.critic.irreversibility import is_irreversible
from agent.critic.conclave import ConclaveCritic

async def _execute_tools(self, tool_calls):
    results = []
    for call in tool_calls:
        irreversible, reason = is_irreversible(call.name, call.args)
        if irreversible and self.critic_enabled:
            verdict = await self._gate_with_critic(call, reason)
            if verdict.decision == "REJECT":
                results.append(self._reject_result(call, verdict))
                continue
            if verdict.decision == "ESCALATE":
                approval = await self._create_pending_approval(call, verdict)
                results.append(self._wait_for_approval(approval))
                continue
            # APPROVE → segue execução normal
        result = await self._execute_single(call)
        results.append(result)
    return results

async def _gate_with_critic(self, call, reason):
    critic = ConclaveCritic()
    try:
        return await asyncio.wait_for(
            critic.evaluate(
                action=f"{call.name}({call.args})",
                irreversible=True,
                reason=reason,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        return CriticVerdict(decision="ESCALATE", reason="critic timeout")
```

### 3. Tabela de approvals (se ainda não existe)

Verifica:
```bash
docker compose exec postgres psql -U agent -d agent -c "\d pending_approvals"
```

Se não existir, cria migration `017_pending_approvals.sql`:

```sql
CREATE TABLE IF NOT EXISTS pending_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID,
    tool_name VARCHAR(64) NOT NULL,
    tool_args JSONB NOT NULL,
    critic_verdict JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolved_by VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);
```

Aplica via `docker compose exec postgres psql -U agent -d agent -f /migrations/017_pending_approvals.sql`.

### 4. Notificar via Telegram

No gateway Node, adiciona handler que escuta Redis pub/sub no canal `approvals:new` e manda mensagem pro chat configurado com botões inline "Aprovar" / "Rejeitar".

Se isso já existir (Fase 5), só conecta. Senão, deixa stub que loga warning e cria approval com status `pending`.

### 5. Testes

`core/tests/unit/test_irreversibility.py` — 8 casos:
- read_file → não irreversível
- write_file em /tmp → não
- write_file em /home → sim
- shell `ls -la` → não
- shell `rm -rf /tmp/x` → sim
- shell `git push` → sim
- send_telegram → sim
- tool desconhecida → sim (fail-safe)

`core/tests/integration/test_critic_gating.py`:
- Mock Critic respondendo APPROVE → tool executa
- Mock Critic respondendo REJECT → tool não executa, result tem `blocked_by_critic=true`
- Mock Critic respondendo ESCALATE → cria `pending_approvals` row, aguarda
- Critic timeout → trata como ESCALATE

### 6. Validar end-to-end

```bash
cd ~/Desktop/agent
docker compose up -d
sleep 5
PYTHONPATH=core/src ./.venv312/bin/python -c "
from agent.ai_agent import AIAgent
import asyncio
async def main():
    agent = AIAgent(critic_enabled=True)
    # tenta ação irreversível
    r = await agent.run('apague todos os arquivos em /home/user/important')
    print(r)
asyncio.run(main())
"

docker compose exec postgres psql -U agent -d agent -c \
  "SELECT count(*) FROM critic_evaluations WHERE created_at > NOW() - INTERVAL '5 minutes';"
docker compose exec postgres psql -U agent -d agent -c \
  "SELECT count(*) FROM pending_approvals WHERE status='pending';"
```

Esperado: pelo menos 1 critic_evaluation registrada, pelo menos 1 pending_approval criada, NENHUM arquivo deletado.

### 7. Suite completa

```bash
cd core
PYTHONPATH=src ../.venv312/bin/python -m pytest -x --tb=short
```

### 8. Commit + tag + push

```bash
git add -A
git commit -m "feat(d4): Conclave Critic gateia ações irreversíveis no mission flow

- agent/critic/irreversibility.py classifica tool calls
- AIAgent._execute_tools hookea Critic antes de exec
- REJECT bloqueia, ESCALATE cria pending_approval, APPROVE libera
- Timeout 30s → fallback ESCALATE
- Migration 017 (se necessária) pra pending_approvals
- 8 unit + 4 integration tests

Resolve: D.4 do FASE_D_BACKLOG.md"

git tag fase-d4-done
git push origin main --tags
```

### 9. Relatório

`RELATORIO_D4.md`:
```markdown
# Relatório Fase D.4
- [x] Hook implementado em _execute_tools
- [x] 12 testes passando
- [x] Smoke E2E: critic_evaluations +1, pending_approvals +1, NENHUM dano
- Bugs encontrados: [lista]
- Próximo: prompt 04_FASE_F9_voyager_validation.md
```

## Critério de aceite

- 12+ testes novos verdes
- Smoke E2E grava registros em `critic_evaluations` e `pending_approvals`
- Nenhuma ação irreversível executou no smoke (provando que gating funciona)
- Tag `fase-d4-done`

## NÃO faça

- Não gateia ações reversíveis (latência).
- Não bloqueia tools de leitura.
- Não desliga o gating "pra acelerar testes".
