# BUG F5 — ApprovalManager.create() não serializa skill_args para jsonb

**Descoberto em:** C.1 (Runtime validation F5)  
**Data:** 2026-06-06  
**Status:** DOCUMENTADO — não corrigido

---

## Sintoma

`ApprovalManager.create()` falha com:

```
asyncpg.exceptions.DataError: invalid input for query argument $4:
  {'to': 'test@example.com', ...} (expected str, got dict)
```

## Reprodução mínima

```python
import asyncio, asyncpg
from agent.approvals.manager import ApprovalManager

async def repro():
    pool = await asyncpg.create_pool(
        'postgresql://agent:qualquercoisa123@localhost:5432/agent',
        min_size=1, max_size=2,
    )
    mgr = ApprovalManager(db_pool=pool)
    await mgr.create(
        session_id='probe-session',
        skill_name='mock_send_email',
        skill_args={'to': 'test@example.com', 'subject': 'T', 'body': 'B'},
        summary='Probe',
        channel='test',
    )

asyncio.run(repro())
# → DataError: invalid input for query argument $4: ... (expected str, got dict)
```

## Localização

**Arquivo:** `core/src/agent/approvals/manager.py`  
**Método:** `ApprovalManager.create()` (~linha 66)

```python
await conn.execute(
    """
    INSERT INTO pending_approvals
        (id, session_id, skill_name, skill_args, summary, channel, channel_ref, expires_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """,
    approval_id,
    session_id,
    skill_name,
    skill_args,       # ← BUG: passa dict direto para coluna jsonb
    summary,
    channel,
    channel_ref or {},  # ← MESMO BUG: channel_ref também é jsonb
    expires_at,
)
```

## Causa Raiz

`asyncpg` não aceita `dict` Python diretamente para parâmetros de colunas `jsonb`. É necessário serializar com `json.dumps()` antes de passar para o parâmetro.

## Padrão correto no projeto

Todos os outros módulos que inserem jsonb usam `json.dumps()` explícito:

| Arquivo | Linha | Padrão correto |
|---------|-------|----------------|
| `tasks/store.py` | ~139 | `json.dumps(raw_trace, ensure_ascii=False) if raw_trace else None` |
| `missions/store.py` | ~122 | `json.dumps(success_criteria, ensure_ascii=False)` |
| `missions/store.py` | ~128 | `json.dumps(metadata or {}, ensure_ascii=False)` |
| `missions/store.py` | ~273 | `json.dumps(result, ensure_ascii=False) if result ...` |
| `critic/critic.py` | (jsonb insert) | `json.dumps(...)` |

## Impacto

- `ApprovalManager.create()` NUNCA funcionou com Postgres real
- Qualquer skill com `requires_approval: true` (ex: `mock_send_email`) não pode criar aprovações
- O Docker core provavelmente nunca criou uma linha em `pending_approvals` via SkillManager
- `channel_ref or {}` (segundo dict passado direto) teria o mesmo erro

## Colunas afetadas em `pending_approvals`

```sql
skill_args   jsonb  NOT NULL
channel_ref  jsonb  NOT NULL  DEFAULT '{}'::jsonb
```

## Correção proposta (NÃO APLICADA)

Em `ApprovalManager.create()`, substituir:
```python
skill_args,
channel_ref or {},
```
por:
```python
json.dumps(skill_args, ensure_ascii=False),
json.dumps(channel_ref or {}, ensure_ascii=False),
```

E importar `json` no topo do arquivo.

---

**Bloqueador para:** C.1 (Runtime validation F5 — fluxo de aprovações)
