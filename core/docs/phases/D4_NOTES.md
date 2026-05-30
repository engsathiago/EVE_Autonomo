# D.4 — Notas técnicas e lições aprendidas

## Lição aprendida — Gap 1 e Gap 2 (D.4.1)

A D.4 fechou com 5 commits e testes verdes mas nunca foi exercitada
pelo caminho real do server.py. Os testes da D.4 injetavam
`MissionExecutor` diretamente, mascarando que `server.py` nunca o
instanciava. Mesmo padrão da Fase A: artefato existe, nunca rodou.

**Causa:** testes unit injetam dependências diretamente no objeto testado.
Isso isola bem a lógica interna, mas não detecta que o objeto nunca é
criado nem passado para quem precisa dele no caminho de produção.

**Regra nova:** toda sub-fase D que toca em wiring precisa de PELO
MENOS um integration test que verifique o objeto via instanciação que
espelha o padrão do server.py — não via injeção direta no teste.

Exemplo implementado em D.4.1:
```
tests/integration/test_d4_wired_in_server.py
  test_autonomous_loop_has_executor_wired   ← Gap 1
  test_subagent_receives_critic_via_pool    ← Gap 2
```

---

## Gaps encontrados no replay D.4 (2026-05-30)

### Gap 1 — MissionExecutor não instanciado em server.py (CORRIGIDO em D.4.1)

`server.py` nunca criava `MissionExecutor` nem o passava para
`AutonomousLoop(executor=...)`. Com `executor=None`, o loop usava o
caminho legado onde `Decision(tool_name="orchestrator_dispatch")` é
criado — `needs_critic()` retorna False → Critic nunca chamado.

**Fix D.4.1:** server.py cria `MissionExecutor` em phase 7 e passa como
`executor=_mission_executor` para `AutonomousLoop`.

### Gap 2 — Critic ausente em subagentes STRATEGIC (CORRIGIDO em D.4.1)

`build_subagent()` não recebia `critic` nem `mission_id`. Para o
caminho STRATEGIC (usado por missões), os subagentes eram criados sem
`AIAgent._critic` — o hook em `_execute_tools` nunca disparava.

**Fix D.4.1:** 
- `SubagentPool` recebe `critic` no construtor e o passa para `build_subagent`
- `build_subagent` recebe `critic: Critic | None` e `mission_id: UUID | None`
- `_run_strategic` extrai `mission_id` de `task.channel_ref` e popula `ctx.mission_id`
- Em `server.py` (phase 7): `_subagent_pool._critic = _critic` e
  `_orchestrator._critic = _critic` + `_orchestrator._db_pool = _memory_store._pool`
  (retroativos, pois pool/orchestrator são criados em phase 6 antes do Critic)

### Gap 3 — Critic sem db_pool em subagentes (CORRIGIDO em D.4.2)

`build_subagent` não recebia `db_pool`. Quando o Critic avaliava uma tool
irreversível em um subagente, a avaliação era executada mas não persistia
em `critic_evaluations` (a tabela ficava sem a linha de evidência).

O bloqueio funcionava (critic_blocked=True era setado e propagado ao
MissionExecutor), mas a auditoria em DB ficava incompleta.

**Fix D.4.2:**
- `build_subagent` ganha param `db_pool: Any | None = None` e propaga pro AIAgent
- `SubagentPool.__init__` ganha `db_pool`, armazena em `self._db_pool`
  e passa pro `build_subagent` em `_run_one`
- `server.py` injeta retroativo: `_subagent_pool._db_pool = _memory_store._pool`
- Integration test `test_subagent_critic_writes_to_db` garante que
  `critic_evaluations` recebe INSERT com `mission_id` no caminho STRATEGIC

---

## Quota Anthropic — bloqueio do replay LLM real

A conta Anthropic atingiu o limite de uso em 2026-05-30.
Replay LLM real bloqueado até **2026-06-01 00:00 UTC**.

`MODEL_FALLBACK_CHAIN` está vazio em `docker-compose.d5.yml` — sem Ollama
configurado como fallback. Para replay antes de 2026-06-01, configurar:
```yaml
MODEL_FALLBACK_CHAIN: "ollama:qwen2.5:7b"
```
e garantir que Ollama esteja rodando com o modelo disponível.

---

## Arquivo D4_REPLAY_RESULTS.md

Histórico do replay original (2026-05-30) e resultado após fix D.4.1.
Ver: `core/docs/phases/D4_REPLAY_RESULTS.md`
