# BUG F5 — ApprovalManager: jsonb sem json.dumps + desserialização quebrada

**Descoberto em:** C.1 (Runtime validation F5)  
**Data:** 2026-06-06  
**Status:** RESOLVIDO

---

## BUG F5-A — create() não serializa skill_args/channel_ref para jsonb

### Sintoma

`ApprovalManager.create()` falha com:

```
asyncpg.exceptions.DataError: invalid input for query argument $4:
  {'to': 'test@example.com', ...} (expected str, got dict)
```

### Localização

**Arquivo:** `core/src/agent/approvals/manager.py`  
**Método:** `ApprovalManager.create()`

```python
# ANTES (quebrado):
skill_args,       # dict direto → DataError para coluna jsonb
channel_ref or {} # idem
```

### Causa Raiz

`asyncpg` não aceita `dict` Python para `jsonb`. Requer `json.dumps()`.
Todos os outros módulos do projeto usam `json.dumps()` explícito (`tasks/store.py`,
`missions/store.py`, `critic/critic.py`). Esse inconsistência passou despercebida
porque `ApprovalManager.create()` nunca foi exercitada contra Postgres real.

### Impacto

- `create()` NUNCA funcionou com Postgres real
- Qualquer skill com `requires_approval: true` (ex: `mock_send_email`) incapaz de criar aprovações
- Docker core nunca criou linha em `pending_approvals` via SkillManager

---

## BUG F5-B — get()/decide()/list_pending() não deserializam UUID e jsonb

### Sintoma (descoberto ao testar o fix F5-A)

`ApprovalManager.decide()` falha com Pydantic ValidationError:

```
pydantic_core.ValidationError: 3 validation errors for ApprovalState
id
  Input should be a valid string [type=string_type, input_value=UUID('...'), input_type=UUID]
skill_args
  Input should be a valid dictionary [type=dict_type, input_value='{"to": "x@y.com"...}', input_type=str]
channel_ref
  Input should be a valid dictionary [type=dict_type, input_value='{"chat_id": "123"}', input_type=str]
```

### Localização

**Arquivo:** `core/src/agent/approvals/manager.py`  
Todos os métodos que constroem `ApprovalState(**dict(row))`:
- `get()` — linha ~134
- `decide()` — linha ~155 (SELECT) e ~182 (RETURNING *)  
- `list_pending()` — linha ~226

### Causa Raiz

asyncpg retorna:
- coluna `uuid` → Python `uuid.UUID` (não `str`)
- coluna `jsonb` → Python `str` JSON-encoded (sem codec registrado)

`ApprovalState.id: str` e `ApprovalState.skill_args: dict[str, Any]` exigem os tipos Python corretos. Sem conversão, Pydantic rejeita os valores.

---

## Resolução

### Arquivos modificados

**`core/src/agent/approvals/manager.py`** (todos no mesmo commit):

1. **Adicionado `import json`** no topo
2. **`create()`** — `skill_args` e `channel_ref or {}` envolvidos em `json.dumps(..., ensure_ascii=False)`
3. **Adicionado helper `_row_to_state(row)`** que converte:
   - `data["id"] = str(data["id"])` → UUID → str
   - `data["skill_args"] = json.loads(val)` → str JSON → dict
   - `data["channel_ref"] = json.loads(val)` → str JSON → dict
4. **Substituído todos os `ApprovalState(**dict(row))`** por `_row_to_state(row)` em `get()`, `decide()` (×2), `list_pending()`

### Testes que cobrem

| Teste | Tipo | Cobre |
|-------|------|-------|
| `tests/approvals/test_approval_jsonb_serialization.py` | unit (3 testes) | F5-A: skill_args e channel_ref serializado como str |
| `tests/runtime/test_phase_f5_real.py` | runtime (1 teste) | F5-A + F5-B end-to-end: create → DB → decide → status=approved |

### Nota sobre Docker core

O core Docker roda imagem buildada (sem hot-reload). Necessita rebuild para pegar o fix:
```bash
docker compose build core && docker compose up -d core
```
O teste runtime usa `manager.decide()` diretamente (permitido pelo spec) em vez do
endpoint HTTP, pois o Docker core ainda tem o código antigo.
