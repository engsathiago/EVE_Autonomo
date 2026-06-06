# BUG_PATTERN_MAP — sites do padrão "persiste sem validar execução"

> Gerado em 2026-05-25 como parte da Fase B.
> Metodologia: grep + leitura direta dos arquivos. Nenhum código alterado.
> Confirmar ANTES de iniciar B.2.

---

## Site 1 — Mission executor (causa-raiz primária)

**Arquivo:** `core/src/agent/autonomous/loop.py`  
**Função:** `AutonomousLoop._dispatch_step()`  
**Linhas:** 229–252

```python
# linha 232
result = await self._orchestrator.route(task)
# linha 233–237
await self._mission_store.update_step(
    step.id,
    status="done",                                  # ← SEMPRE done
    result={"text": (result.final_text or "")[:1000]},  # ← prosa embrulhada aceita como result
)
return True
```

**Padrão atual:** `orchestrator.route(task)` retorna `AgentResult`, que só tem `final_text` (string de texto). Não tem campo de tool calls. O executor pega `final_text` embrulhado em `{"text": "..."}` e marca `status=done` incondicionalmente — qualquer resposta textual é aceita como execução bem-sucedida.

**Raiz estrutural:** `AgentResult` (em `core/src/agent/core.py:33`) não expõe `tools_called`:

```python
class AgentResult(BaseModel):
    final_text: str
    iterations: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    duration_s: float
    conversation_id: str | None = None
    approval_request: dict | None = None
    # ← AUSENTE: tool_calls_made: list[str]
```

`AIAgent.run()` (linhas 93–213) itera sobre turns, chama `response.tool_calls` por turn, mas não acumula esse dado no `AgentResult` final.

**Como detectar manualmente:** `mission_steps` com `status=done` cujo `result->>'text'` contém frases como "não tenho acesso", "entendi", "preciso que você" — prosa pura embrulhada em `{"text": "..."}`.

**Fix necessário:**
1. Adicionar `tool_calls_made: list[str]` ao `AgentResult`
2. Acumular chamadas em `AIAgent.run()` com `all_tool_calls.extend([c["name"] for c in response.tool_calls])`
3. No `_dispatch_step`: chamar `analyze_turn(result)` e rejeitar `PROSE_ONLY`

---

## Site 2 — Subagent runner (`tools_used` registra tools disponíveis, não chamadas)

**Arquivo:** `core/src/agent/subagents/pool.py`  
**Função:** `SubagentPool._run_one()`  
**Linhas:** 138–146

```python
await self._task_store.record_subagent_run(
    task_id=child_task.id,
    parent_task=parent_task.id,
    tools_used=context.tools_allowed,  # ← BUG: lista de tools DISPONÍVEIS no contexto
    duration_ms=duration_ms,
    success=(status == TaskStatus.DONE),  # ← True se não houve exception ou approval_request
    summary=result.final_text[:500] if result.final_text else "",
    ...
)
```

**Padrão atual:** `tools_used` recebe `context.tools_allowed` — o set de tools que foi injetado no contexto do subagente (ex: `["web_search", "read_file", "salvar_memoria", "ler_memoria"]`). Isso registra disponibilidade, não uso.

`success` é derivado de `status == TaskStatus.DONE`, que é `True` quando `result.approval_request` é None — ou seja, se o LLM respondeu texto sem levantar exception nem pedir approval, o subagente é considerado bem-sucedido.

O mesmo bug ocorre no path de timeout (linhas 103–110): `tools_used=context.tools_allowed` e `success=False` (timeout já corretamente marca falha, mas o campo `tools_used` ainda é incorreto).

**Como detectar manualmente:** `subagent_runs` com `tools_used = {web_search, read_file, ...}` e `summary` sendo prosa ("não tenho acesso...") — o summary e o tools_used contradizem entre si.

**Fix necessário:**
1. `AgentResult` precisa ter `tool_calls_made: list[str]` (depende do fix do Site 1)
2. Em `pool.py`: `tools_used=result.tool_calls_made` (tools chamadas de fato)
3. `success` deve ser `(status == TaskStatus.DONE) AND len(result.tool_calls_made) > 0`  
   *exceto* quando subagente é explicitamente de planejamento (ver `allow_planning` no spec B.2)

---

## Site 3 — Critic nunca ativado no flow de missões

**Arquivo:** `core/src/agent/autonomous/loop.py` + `core/src/agent/critic/irreversible.py`  
**Função:** `AutonomousLoop._dispatch_step()`, linhas 188–221

```python
decision = Decision(
    tool_name="orchestrator_dispatch",   # ← nome genérico, não é tool real
    tool_args={"step": step.description, "mission": mission.title},
    context_summary=...,
    tier=ExecutionTier.STRATEGIC,         # ← nunca EPIC
    mission_id=mission.id,
)

if self._critic is not None and needs_critic(decision):   # ← SEMPRE False
```

**Por que `needs_critic()` sempre retorna False aqui:**

```python
def needs_critic(decision, cost_threshold_usd=0.50):
    return (
        is_irreversible(decision.tool_name)       # "orchestrator_dispatch" NÃO está na lista
        or decision.tier == ExecutionTier.EPIC    # é STRATEGIC
        or decision.estimated_cost_usd >= 0.50   # default 0.0
        or decision.affects_external_world        # default False
        or decision.is_first_of_its_kind          # default False
    )
```

`IRREVERSIBLE_TOOLS` contém: `send_telegram, send_email, post_social_media, git_push, fs_delete, execute_shell, transfer_money, delete_record, execute_sql_write, exec_sandbox`. Não contém `orchestrator_dispatch`.

**Consequência:** O Critic está wired no `server.py` (quando `settings.critic.enabled = True`, padrão), mas nunca é ativado pelo loop de missões. Os 9 `critic_evaluations` no banco foram gerados diretamente via API (`POST /v1/critic/evaluate`), não pelo flow de missões — confirmado pelo fato de todos terem `mission_id = NULL`.

**Natureza deste site:** diferente dos Sites 1 e 2, este não é um bug de "persistir sem validar" — é uma **conexão ausente**: o Critic existe mas é chamado com o objeto errado (`orchestrator_dispatch` em vez da tool real que o LLM vai usar). O ponto de avaliação correto seria APÓS a execução do LLM, avaliando as tool calls reais — não ANTES, avaliando uma decisão de despacho genérica.

**Complexidade:** Maior que os Sites 1 e 2. O Critic foi projetado para avaliar PRÉ-execução (`is_irreversible`), mas o mecanismo de detecção funciona com tool names reais. Para funcionar corretamente no loop de missões, precisaria ser chamado por tool call (dentro do `AIAgent`) não por step dispatch (no `AutonomousLoop`).

**Decisão:** Ver seção "Recomendação" abaixo.

---

## Sites adicionais encontrados durante busca

### Site 2b — Mesmo bug no path de timeout (pool.py:103-110)
Também usa `tools_used=context.tools_allowed` em vez de ferramentas reais chamadas. Mesmo fix do Site 2.

### Não-site: `api/missions.py`
`update_status` é puro endpoint REST para mudança manual de status (ex: usuário pausar missão). Não envolve LLM. Sem bug aqui.

### Não-site: `tasks/store.py:record_subagent_run`
É só o DAO. O bug está em quem chama, não no DAO. Fix vai no `pool.py`.

### Não-site: `skills/manager.py:203` e `skills/template_runner.py:169`
`success = True` em skill invocations — são atribuições após execução real da skill. A skill runner já tem validação própria (exceções propagam, linter, smoke run). Não é o mesmo padrão.

---

## Mapa de dependências entre sites

```
AgentResult.tool_calls_made (AUSENTE)
         │
         ├── Site 1 fix: AIAgent.run() acumula tool calls → AgentResult.tool_calls_made
         │         └── loop.py usa analyze_turn(result) → rejeita PROSE_ONLY
         │
         └── Site 2 fix: pool.py usa result.tool_calls_made → tools_used real
                   └── success = DONE AND len(tool_calls_made) > 0

Site 3 (Critic):
  → Complexidade maior, requer hook dentro de AIAgent (não no loop)
  → Candidato para Fase D separada (não bloqueia Sites 1 e 2)
```

**Site 3 é independente dos Sites 1 e 2 para fins de fix.**

---

## Recomendação para B.2–B.4

### Implementar (Fase B)

1. **B.2 — `execution/validation.py`:** helper puro `analyze_turn(result)` que interpreta `AgentResult`
2. **B.3.1 — `core.py` + `loop.py`:** adicionar `tool_calls_made` ao `AgentResult`; `_dispatch_step` valida
3. **B.3.2 — `pool.py`:** `tools_used = result.tool_calls_made`; `success` condicionado a tool calls

### NÃO implementar em Fase B (propor Fase D)

4. **Site 3 — Critic no loop:** requer redesign do ponto de intercepção (de pré-dispatch para pós-execution). Pode ser feito via hook em `AIAgent._execute_tools()` para tools irreversíveis, mas é mudança de escopo. Documentar e propor Fase D.

---

*Mapeamento concluído em 2026-05-25. Nenhum arquivo de código alterado.*
