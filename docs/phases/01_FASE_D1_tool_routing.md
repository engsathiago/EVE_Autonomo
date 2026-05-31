# FASE D.1 — Tool Routing por Step

Projeto: **EVE_Autonomo** em `~/Desktop/agent`. Repo: `github.com/engsathiago/EVE_Autonomo`.
Estado: `main` em `fase-b-done`. Python 3.12 em `.venv312/`.

## Objetivo único

Implementar roteamento de tools por step da missão e por tier do subagent, de forma que cada step receba apenas as tools que precisa. Hoje subagents STRATEGIC não têm `write_file`/`list_dir`, que é a causa raiz de várias fases terem ficado teóricas.

## Regras duras (NÃO QUEBRAR)

1. **NUNCA pergunta nada.** Decide e executa.
2. **NUNCA usa `sed` ou heredoc** pra editar Python. Use `view` → `str_replace` ou `create_file`.
3. **NUNCA hardcode API keys.** Tudo em `.env`.
4. **NUNCA desliga sandbox.**
5. **NUNCA marca fase como done com teste falhando.** Se falhar, documenta e tag fica `fase-d1-partial`.
6. **Se trava em decisão de design**, escolhe a opção mais simples e documenta em `DECISOES_D1.md`. Não pergunta.
7. **Se algo fora do escopo da D.1 está quebrado**, anota em `BUGS_ENCONTRADOS_D1.md` e segue.

## Passos

### 1. Mapear estado atual

```bash
cd ~/Desktop/agent
git status
git log --oneline -5
grep -rn "tools.*=\|allowed_tools\|tool_set" core/src/agent/execution/ core/src/agent/subagents/ | head -50
```

Identifica:
- Onde subagents recebem lista de tools hoje
- Se existe alguma noção de "tool set por tier"
- Onde mission steps definem o que precisam executar

Salva achados em `D1_MAPEAMENTO.md` na raiz.

### 2. Definir tool sets

Cria `core/src/agent/execution/tool_routing.py`:

```python
"""Roteamento de tools por step e por tier de subagent."""
from enum import Enum
from typing import Set

class ToolSet(str, Enum):
    READ_ONLY = "read_only"      # read_file, list_dir, web_search
    WRITE = "write"               # + write_file, shell
    NETWORK = "network"           # + web_fetch, http
    FULL = "full"                 # tudo

TOOL_SET_DEFINITIONS: dict[ToolSet, Set[str]] = {
    ToolSet.READ_ONLY: {"read_file", "list_dir", "web_search"},
    ToolSet.WRITE: {"read_file", "list_dir", "web_search", "write_file", "shell"},
    ToolSet.NETWORK: {"read_file", "list_dir", "web_search", "web_fetch"},
    ToolSet.FULL: {"read_file", "list_dir", "web_search", "write_file", "shell", "web_fetch"},
}

# Tier defaults — usado quando o step não declara tool_set explícito
TIER_DEFAULTS: dict[str, ToolSet] = {
    "INSTANT": ToolSet.READ_ONLY,
    "FAST": ToolSet.WRITE,
    "STRATEGIC": ToolSet.FULL,      # ← era o bug: estava como READ_ONLY
    "EPIC": ToolSet.FULL,
}

def resolve_tools_for_step(step_tool_set: str | None, tier: str) -> Set[str]:
    """Resolve tools de um step. Step explícito vence; senão usa default do tier."""
    if step_tool_set:
        try:
            return TOOL_SET_DEFINITIONS[ToolSet(step_tool_set)]
        except ValueError:
            pass
    default = TIER_DEFAULTS.get(tier, ToolSet.READ_ONLY)
    return TOOL_SET_DEFINITIONS[default]
```

### 3. Migration 016 — adicionar coluna `tool_set` em `mission_steps`

```bash
ls core/migrations/ | sort | tail -3
# pega o próximo número (016)
```

Cria `core/migrations/016_mission_step_tool_set.sql`:

```sql
ALTER TABLE mission_steps
ADD COLUMN IF NOT EXISTS tool_set VARCHAR(20) DEFAULT NULL;

COMMENT ON COLUMN mission_steps.tool_set IS
'Tool set explícito do step: read_only|write|network|full. NULL = usa default do tier.';

CREATE INDEX IF NOT EXISTS idx_mission_steps_tool_set ON mission_steps(tool_set)
WHERE tool_set IS NOT NULL;
```

### 4. Integrar no mission executor

Localiza onde o mission executor instancia o subagent (provavelmente `core/src/agent/missions/executor.py` ou `core/src/agent/execution/mission_runner.py`). Substitui a passagem hardcoded de tools por:

```python
from agent.execution.tool_routing import resolve_tools_for_step

allowed_tools = resolve_tools_for_step(
    step_tool_set=step.tool_set,
    tier=step.tier or mission.tier,
)
# passar allowed_tools pro subagent ao invés da lista fixa antiga
```

### 5. Integrar no subagent runner

Em `core/src/agent/subagents/runner.py` (ou onde o subagent registra suas tools), aceita `allowed_tools: set[str] | None` e filtra o `ToolRegistry` por esse set antes de passar pro LLM.

Se `allowed_tools` for `None`, mantém comportamento atual (compatibilidade pra trás).

### 6. Testes de regressão

Cria `core/tests/unit/test_tool_routing.py` com 5 cenários:

1. Step com `tool_set='read_only'` → set certo
2. Step sem `tool_set` + tier `STRATEGIC` → `FULL` (regressão do bug)
3. Step sem `tool_set` + tier `INSTANT` → `READ_ONLY`
4. Step com `tool_set` inválido → fallback pro default do tier
5. Tier desconhecido → fallback pra `READ_ONLY`

Cria `core/tests/integration/test_mission_step_routing.py`:
- Cria mission com 2 steps (um INSTANT só leitura, um STRATEGIC com escrita)
- Roda executor mockado
- Valida que cada subagent recebeu o tool set correto

### 7. Validar

```bash
cd core
PYTHONPATH=src ../.venv312/bin/python -m pytest tests/unit/test_tool_routing.py tests/integration/test_mission_step_routing.py -v
PYTHONPATH=src ../.venv312/bin/python -m pytest -x --tb=short
```

Tudo verde antes de seguir.

### 8. Aplicar migration

```bash
docker compose exec postgres psql -U agent -d agent -f /migrations/016_mission_step_tool_set.sql
```

Se docker não estiver rodando, anota em `BUGS_ENCONTRADOS_D1.md` e segue (migration ficou pendente).

### 9. Commit + tag + push

```bash
cd ~/Desktop/agent
git add -A
git commit -m "feat(d1): tool routing por step e tier

- Novo módulo agent/execution/tool_routing.py com ToolSet enum
- Tier defaults: STRATEGIC e EPIC agora têm FULL (era READ_ONLY)
- Migration 016 adiciona coluna tool_set em mission_steps
- Mission executor e subagent runner respeitam tool_set por step
- 5 testes unit + 1 integration de regressão

Resolve: D.1 do FASE_D_BACKLOG.md
Causa raiz de várias fases F5-F13 ficarem teóricas."

git tag fase-d1-done
git push origin main --tags
```

### 10. Relatório final

Cria `RELATORIO_D1.md` na raiz com:

```markdown
# Relatório Fase D.1

## Entregue
- [x] tool_routing.py
- [x] Migration 016 (status: aplicada / pendente)
- [x] Mission executor integrado
- [x] Subagent runner integrado
- [x] 6 testes passando
- [x] Tag fase-d1-done

## Bugs encontrados fora do escopo
[lista do BUGS_ENCONTRADOS_D1.md]

## Decisões tomadas sem consultar
[lista do DECISOES_D1.md]

## Próximo passo
Cola prompt 02_FASE_D5_revalidacao.md no próximo Claude Code.
```

## Critério de aceite

- 6+ testes novos passando
- Tag `fase-d1-done` empurrada
- `RELATORIO_D1.md` na raiz
- Suite completa: 87+ testes verdes (81 antigos + 6 novos)

## Se falhar

- Bug isolado: documenta em `BUGS_ENCONTRADOS_D1.md`, tag `fase-d1-partial`
- Bug arquitetural (ex: mission executor não existe como pensei): documenta em `D1_MAPEAMENTO.md` o que achou, tag `fase-d1-blocked`, próximo prompt vai ter que adaptar

**NÃO interrompe pra perguntar.** Executa até o fim, documenta, sai.
