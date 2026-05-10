# Fase 7 — Missões Persistentes + Crítico Autônomo

**Status:** spec  
**Branch:** `feature/phase-7-missions-critic`  
**Pré-requisitos:** Fase 6 concluída e mergeada em `main` (tag `phase-6-done`).  
**Estimativa:** 6–9 dias de trabalho focado.

---

## 1. Objetivo

Dar ao agente **memória de objetivo de longo prazo** (missões que sobrevivem a restart, cobrem dias/semanas) e **freio cognitivo** (Crítico Autônomo) que questiona decisões irreversíveis antes da execução.

A Fase 6 ensinou o agente a **decompor** uma tarefa em subagentes paralelos. A Fase 7 ensina a **persistir** intenções entre execuções e a **revisar criticamente** decisões caras antes de tomá-las.

### O que muda na prática

Hoje (pós-F6):
```
"Pesquisa concorrentes da empresa X" → orchestrator → 3 subagentes em paralelo → resultado
```

Pós-F7:
```
"Lança o canal de cortes de saúde mental até dia 30" → cria Mission persistente
  → AutonomousLoop dispara passos diários
    → cada passo passa pelo Critic se for irreversível
      → sucesso/falha/rollback registrado
        → MissionReflector roda no fim e gera insight
```

---

## 2. Componentes novos

### 2.1 `MissionStore` (`agent/missions/store.py`)

Persistência de missões em Postgres.

**Schema (migration 007):**

```sql
CREATE TABLE missions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    objective TEXT NOT NULL,             -- descrição em prosa do "feito" final
    success_criteria JSONB NOT NULL,     -- lista de critérios objetivos verificáveis
    deadline TIMESTAMPTZ,                -- nullable; missão pode não ter prazo
    status TEXT NOT NULL CHECK (status IN ('active','paused','done','abandoned','failed')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    source TEXT,                         -- telegram, cli, cron
    source_ref TEXT,                     -- chat_id, user_id, etc
    parent_mission_id UUID REFERENCES missions(id),  -- missão pode ter sub-missões
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_missions_status ON missions(status) WHERE status = 'active';
CREATE INDEX idx_missions_deadline ON missions(deadline) WHERE status = 'active';

CREATE TABLE mission_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    sequence INT NOT NULL,               -- ordem dentro da missão
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','running','done','failed','skipped')),
    task_id UUID REFERENCES tasks(id),   -- liga ao sistema de tasks da F6
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error TEXT,
    UNIQUE (mission_id, sequence)
);

CREATE INDEX idx_mission_steps_mission ON mission_steps(mission_id, sequence);
CREATE INDEX idx_mission_steps_pending ON mission_steps(mission_id, status) WHERE status = 'pending';

CREATE TABLE mission_reflections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    delivered TEXT NOT NULL,             -- ENTREGUE: o que foi feito
    quality_assessment TEXT NOT NULL,    -- QUALIDADE: avaliação honesta
    next_action TEXT,                    -- PRÓXIMO: ação sugerida
    learned TEXT NOT NULL,               -- APRENDIDO: insight pra memória reflexiva
    created_at TIMESTAMPTZ DEFAULT now()
);
```

**API pública:**

```python
class MissionStore:
    async def create(self, *, title: str, objective: str,
                     success_criteria: list[dict], deadline: datetime | None,
                     source: str, source_ref: str | None,
                     parent_mission_id: UUID | None = None) -> Mission: ...

    async def get(self, mission_id: UUID) -> Mission: ...
    async def list_active(self) -> list[Mission]: ...
    async def list_by_deadline(self, before: datetime) -> list[Mission]: ...

    async def add_step(self, mission_id: UUID, *, description: str,
                       sequence: int | None = None) -> MissionStep: ...
    async def get_pending_steps(self, mission_id: UUID) -> list[MissionStep]: ...
    async def update_step(self, step_id: UUID, *,
                          status: str, task_id: UUID | None = None,
                          result: dict | None = None, error: str | None = None) -> None: ...

    async def update_status(self, mission_id: UUID, status: str) -> None: ...
    async def add_reflection(self, mission_id: UUID, reflection: MissionReflection) -> None: ...
```

**Regras invariantes:**
- Nunca deletar missão. `abandoned` é o terminal pra "desistir".
- `success_criteria` é JSONB com formato `[{"criterion": "...", "verifiable_via": "manual|metric|task"}]`. Sem critério → não cria a missão.
- `mission_steps.sequence` é único por missão (forçado pela DB).
- Se `parent_mission_id` existe, missão filha não pode ter status terminal antes da pai. Validado no `update_status`.

### 2.2 `MissionPlanner` (`agent/missions/planner.py`)

Decompõe um objetivo em passos executáveis.

**Fluxo:**

```python
class MissionPlanner:
    def __init__(self, llm: LLMProvider, mission_store: MissionStore): ...

    async def plan(self, objective: str, deadline: datetime | None = None) -> MissionPlan:
        """
        Recebe um objetivo em linguagem natural e devolve:
        - title (curto, <80 chars)
        - success_criteria: lista verificável
        - steps: lista ordenada de descrições de passos
        Não cria a missão ainda — só monta o plano. Quem cria é quem chamou.
        """

    async def replan(self, mission_id: UUID, *, reason: str) -> MissionPlan:
        """
        Gera plano novo a partir do estado atual da missão.
        Chamado quando: passo falha 3x, deadline aproxima e progresso < 30%,
        ou usuário pede replan via CLI/Telegram.
        Reutiliza success_criteria original; só re-decompõe os steps.
        """
```

**Prompt do planner (resumido):**

```
Você é um planejador de missões. Recebe um objetivo em prosa e devolve JSON com:
- title: <80 chars
- success_criteria: lista de objetos {criterion, verifiable_via}
- steps: lista ordenada de descrições curtas (<200 chars cada), cada uma viável como
  uma task da F6 (pode virar INSTANT, FAST, STRATEGIC ou EPIC pelo Orchestrator).

REGRAS:
1. Cada critério em success_criteria precisa ser verificável por alguém que NÃO leu este prompt.
   Errado: "fazer um bom canal". Certo: "publicar 10 cortes em 30 dias".
2. Steps são SEQUENCIAIS por padrão. Marque step com prefixo "[PARALELO N]:" se pode rodar
   em paralelo com o próximo (vira EPIC no Orchestrator).
3. Não invente passos genéricos tipo "fazer pesquisa". Se for pesquisa, especifique sobre o quê.
4. Se objetivo não tem como virar critérios verificáveis, devolve {"error": "objetivo_subjetivo",
   "reason": "..."} — quem chamou decide se aborta ou pede pro usuário refinar.
```

### 2.3 `Critic` (`agent/critic/critic.py`) — Conclave de 3 personas

O componente mais delicado da Fase 7. **Não é classificador.** É um colegiado de 3 prompts diferentes que avalia uma decisão **antes** dela ser executada.

**Quando dispara:**

```python
async def needs_critic(decision: Decision) -> bool:
    return (
        decision.tool_name in IRREVERSIBLE_TOOLS or       # delete, send_email, post_public, transfer
        decision.tier == ExecutionTier.EPIC or            # tarefa cara
        decision.estimated_cost_usd >= 0.50 or            # threshold ajustável
        decision.affects_external_world or                # qualquer write em API externa
        decision.is_first_of_its_kind                     # tool nunca usada com esse padrão de args
    )
```

`IRREVERSIBLE_TOOLS` é definido em `agent/critic/irreversible.py` e é uma lista explícita — começa com:

```python
IRREVERSIBLE_TOOLS = {
    "send_telegram",
    "send_email",
    "post_social_media",
    "git_push",
    "fs_delete",
    "execute_shell",      # qualquer comando bash
    "transfer_money",     # se algum dia existir
    "delete_record",
    "execute_sql_write",  # INSERT/UPDATE/DELETE
}
```

Não é mágica de detecção. É lista mantida à mão. Skill nova precisa declarar `irreversible: true` no manifesto pra entrar.

**As 3 personas:**

```python
class Critic:
    def __init__(self, llm: LLMProvider): ...

    async def evaluate(self, decision: Decision, context: CriticContext) -> CriticVerdict:
        """
        Roda 3 personas em PARALELO (asyncio.gather). Cada uma devolve:
        - approve: bool
        - confidence: 0-1
        - reasoning: prosa curta
        - concerns: lista de strings

        Depois roda um sintetizador que decide o veredito final.
        """
```

**Persona 1 — Técnico (`technical_reviewer`):**

```
Você revisa decisões técnicas de um agente autônomo. Foca em:
- A decisão é tecnicamente correta dado o estado do sistema?
- Os args da tool fazem sentido? Há valores fora do esperado?
- Há condição de corrida, dependência não resolvida, side effect não considerado?
- O agente entende a tool que está usando, ou está chutando?

Devolve JSON: {approve, confidence, reasoning, concerns}.
Aprove só se a decisão for tecnicamente sólida.
```

**Persona 2 — Advogado do diabo (`devils_advocate`):**

```
Você é o advogado do diabo. Sua função é encontrar pelo menos 3 razões pra NÃO
executar essa decisão, mesmo que pareça óbvia. Pergunte:
- E se o pressuposto X estiver errado?
- Quem se prejudica se isso for executado?
- O que acontece no pior caso?
- Existe versão menor/reversível dessa ação que dá mesma informação?

Devolve JSON: {approve, confidence, reasoning, concerns}.
Você só aprova se TODAS as objeções tiverem sido respondidas no contexto.
Default é não aprovar.
```

**Persona 3 — Sintetizador (`synthesizer`):**

```
Você recebe os pareceres do Técnico e do Advogado do Diabo, mais o contexto da decisão.
Sua função NÃO é votar — é DECIDIR.

Regras:
- Se ambos aprovam com confidence >= 0.7, veredito = APPROVE.
- Se ambos rejeitam, veredito = REJECT.
- Se discordam, leia as concerns e decida APPROVE_WITH_MITIGATION (e liste mitigações)
  ou ESCALATE_TO_HUMAN se a decisão for genuinamente ambígua.
- NUNCA invente um meio-termo que ignora a concern principal.

Devolve JSON: {verdict: "approve|reject|approve_with_mitigation|escalate",
              mitigations: [], reasoning, escalation_message}.
```

**Veredito → ação:**

```python
match verdict.verdict:
    case "approve":
        executor.run(decision)
    case "approve_with_mitigation":
        decision.apply_mitigations(verdict.mitigations)
        executor.run(decision)
    case "reject":
        # registra em critic_log, devolve falha controlada pra quem chamou
        raise CriticRejected(verdict.reasoning)
    case "escalate":
        # propaga pro humano via Telegram (Fase 5), bloqueia até resposta
        await approval_gate.request_human(decision, verdict.escalation_message)
```

**Schema (migration 007 cont.):**

```sql
CREATE TABLE critic_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id UUID NOT NULL,           -- liga à decision em decisions table (criada aqui se não existir)
    task_id UUID REFERENCES tasks(id),
    mission_id UUID REFERENCES missions(id),
    technical_verdict JSONB NOT NULL,
    devils_advocate_verdict JSONB NOT NULL,
    synthesizer_verdict JSONB NOT NULL,
    final_verdict TEXT NOT NULL CHECK (final_verdict IN ('approve','reject','approve_with_mitigation','escalate')),
    mitigations JSONB,
    latency_ms INT,
    cost_usd NUMERIC(10,6),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_critic_eval_task ON critic_evaluations(task_id);
CREATE INDEX idx_critic_eval_mission ON critic_evaluations(mission_id);
```

**Política de modelo do Critic:**
- Personas 1 e 2 rodam no **modelo médio** (não o mais barato — barato demais escapa concerns sutis; não o mais caro — chamamos 3x).
- Sintetizador roda no **modelo principal** do agente (decisão final precisa de capacidade plena).
- Toda avaliação é cacheada por hash da decision: mesma decisão idêntica em 60s = mesmo veredito (evita loop caro).

### 2.4 `AutonomousLoop` (`agent/autonomous/loop.py`)

Loop que tira passos pendentes da fila de missões e os entrega ao Orchestrator.

```python
class AutonomousLoop:
    def __init__(self, mission_store, orchestrator, critic, scheduler): ...

    async def tick(self) -> LoopReport:
        """
        Executado pelo scheduler (F6) a cada N minutos (default: 5).
        Em cada tick:
        1. Lista missões ativas com deadline próximo (priority).
        2. Pra cada missão, pega próximo step pendente.
        3. Cria Decision; passa pelo Critic se necessário.
        4. Despacha pro Orchestrator (que vai escolher tier e rodar).
        5. Atualiza step_status quando task termina.
        6. Se todos os steps done → roda MissionReflector → marca missão done.
        """

    async def start(self):
        """Registra tick periódico no scheduler. Idempotente."""

    async def stop(self):
        """Remove tick e drena ticks em andamento."""
```

**Limites do loop (não negociáveis):**

```python
MAX_STEPS_PER_TICK = 3              # não mais que 3 steps disparados por tick
MAX_CONCURRENT_MISSIONS = 5          # limite global
TICK_INTERVAL_MINUTES = 5
MISSION_TIMEOUT_DAYS = 60            # após 60d sem progresso → status='failed'
STEP_FAILURE_RETRY_LIMIT = 3         # depois disso, marca step failed e dispara replan
```

**Anti-padrão crítico:** o loop **não chama LLM diretamente**. Só lê DB, decide o que disparar, e delega pro Orchestrator. Isso impede loop infinito de raciocínio em cima de raciocínio.

### 2.5 `MissionReflector` (`agent/missions/reflector.py`)

Roda **uma vez** quando missão atinge `done`, `abandoned` ou `failed`. Formato fixo, não negociável:

```
ENTREGUE:
<O que de fato saiu da missão. Lista factual, sem adjetivos.>

QUALIDADE:
<Avaliação honesta. Se o resultado foi medíocre, diz medíocre. Se faltou critério, diz qual.>

PRÓXIMO:
<Uma única ação concreta que faria sentido fazer agora. Nullable se nada faz sentido.>

APRENDIDO:
<Um insight ÚTIL pra missões futuras. Não é "fui bem-sucedido". É "descobri que X falha quando Y".>
```

**Implementação:**

```python
class MissionReflector:
    def __init__(self, llm: LLMProvider, mission_store: MissionStore,
                 reflexive_memory: ReflexiveMemory): ...

    async def reflect(self, mission_id: UUID) -> MissionReflection:
        mission = await self.mission_store.get(mission_id)
        steps = await self.mission_store.get_all_steps(mission_id)
        critic_evals = await self.mission_store.get_critic_history(mission_id)

        prompt = self._build_prompt(mission, steps, critic_evals)
        raw = await self.llm.generate(prompt, model="primary", max_tokens=800)
        reflection = self._parse_strict(raw)   # erro se não tiver os 4 campos

        await self.mission_store.add_reflection(mission_id, reflection)
        await self.reflexive_memory.add(reflection.learned, source_mission=mission_id)
        return reflection
```

**`_parse_strict` é estrito de propósito.** Se o LLM devolver formato livre, falha. Reflexão sem os 4 campos não vai pra memória.

### 2.6 `ReflexiveMemory` (`agent/memory/reflexive.py`)

Camada nova de memória, separada da memória semântica que já existe.

**Diferença:**
- Memória semântica (já existe): "fato sobre o mundo" (Thiago mora em SP, podcast X tem CPM alto).
- **Memória reflexiva** (nova): "lição aprendida pelo agente" (sempre que tento agendar cron entre 2h-4h da manhã o servidor X cai; missões de conteúdo precisam de pelo menos 7 dias de buffer).

**Schema:**

```sql
CREATE TABLE reflexive_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight TEXT NOT NULL,
    source_mission_id UUID REFERENCES missions(id),
    embedding VECTOR(1536),              -- pgvector, mesma dim da memória semântica
    relevance_score FLOAT DEFAULT 0.5,
    times_recalled INT DEFAULT 0,
    last_recalled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_reflexive_embedding ON reflexive_memory
    USING hnsw (embedding vector_cosine_ops);
```

**API:**

```python
class ReflexiveMemory:
    async def add(self, insight: str, *, source_mission: UUID | None = None) -> UUID: ...

    async def recall(self, query: str, *, top_k: int = 3) -> list[ReflexiveInsight]:
        """
        Chamado pelo MissionPlanner antes de planejar missão nova.
        Retorna top-k insights relevantes pra contexto.
        Incrementa times_recalled.
        """

    async def decay(self):
        """
        Roda diariamente via cron. Insights nunca recall'd em 60d perdem 0.1 de
        relevance_score por dia. Cai abaixo de 0.1 → marcado como 'forgotten'
        (NÃO deletado, só excluído de recall default).
        """
```

---

## 3. Integrações com fases anteriores

| Fase | Integração |
|---|---|
| **F2 (Memória)** | `ReflexiveMemory` é tabela nova ao lado da memória semântica. Mesmo `EmbeddingProvider`. |
| **F3 (Skills)** | Manifesto de skill ganha campo `irreversible: bool` (default `false`). Critic lê isso. |
| **F4 (Multi-modelo)** | Critic usa modelo médio + principal (ver §2.3). Reflector usa principal. Planner usa médio. |
| **F5 (Telegram)** | Critic com veredito `escalate` chama `approval_gate.request_human` que já existe. |
| **F6 (Cron + Subagentes)** | Steps de missão viram tasks via Orchestrator. Loop registra-se como cron job. |

**Migração de dados:** nenhuma. F7 só adiciona tabelas novas. Migration 007 é puramente aditiva.

---

## 4. CLI nova

```bash
# Missões
agent mission create --objective "lança canal de cortes saúde mental até 30/jun" \
                     --deadline 2026-06-30
# → roda MissionPlanner, mostra plano, pede confirmação, cria missão

agent mission list [--status active|done|all]
agent mission show <id>                  # objetivo, critérios, steps, status
agent mission steps <id>                 # só os steps (com status colorido)
agent mission pause <id>
agent mission resume <id>
agent mission abandon <id> --reason "..."
agent mission replan <id> --reason "..."  # força MissionPlanner.replan()
agent mission reflect <id>                # força MissionReflector mesmo se não terminou

# Critic
agent critic show <task_id>               # mostra os 3 vereditos da última eval
agent critic stats                        # taxa de approve/reject/escalate
agent critic test --tool <tool> --args '{...}'  # roda dry-run sem executar

# Memória reflexiva
agent memory reflexive list [--limit 20]
agent memory reflexive search "<query>"
agent memory reflexive forget <id>        # marca como forgotten manualmente

# Loop autônomo
agent loop status                         # tick atual, missões ativas, próximos passos
agent loop tick-now                       # força tick (debug)
agent loop pause                          # pausa loop globalmente
agent loop resume
```

---

## 5. Testes obrigatórios

### 5.1 Testes unitários

```python
# tests/missions/test_store.py
def test_mission_create_requires_success_criteria()
def test_mission_step_sequence_unique()
def test_child_mission_blocks_parent_status_transition()

# tests/missions/test_planner.py
def test_planner_rejects_subjective_objective()
def test_planner_marks_parallel_steps()
def test_replan_preserves_success_criteria()

# tests/critic/test_personas.py
def test_technical_reviewer_flags_invalid_args()
def test_devils_advocate_default_rejects()
def test_synthesizer_never_invents_middle_ground()

# tests/critic/test_irreversible.py
def test_irreversible_tools_list_is_explicit()
def test_skill_must_declare_irreversible_to_be_critiqued()

# tests/missions/test_reflector.py
def test_reflector_strict_parse_rejects_free_form()
def test_reflector_writes_to_reflexive_memory()

# tests/memory/test_reflexive.py
def test_reflexive_memory_decay_marks_forgotten_not_deleted()
def test_recall_increments_times_recalled()
```

### 5.2 Testes de integração

```python
# tests/integration/test_mission_lifecycle.py
async def test_full_mission_create_plan_execute_reflect():
    """
    Cria missão simples (3 passos triviais).
    Roda 3 ticks do loop.
    Verifica:
    - Cada step virou task.
    - Critic foi chamado nos passos irreversíveis.
    - Reflection criada com 4 campos.
    - Insight foi pra reflexive_memory.
    """

async def test_mission_survives_restart():
    """
    Cria missão.
    Mata processo no meio do step 2.
    Sobe processo de novo.
    Step 2 retoma pendente, step 3 espera.
    """

async def test_critic_escalates_to_telegram():
    """
    Mock decision com tool irreversível e args ambíguos.
    Critic devolve 'escalate'.
    Verifica que mensagem chegou no approval_gate da F5.
    """

async def test_replan_after_3_step_failures():
    """
    Step com retry_count = 3.
    Loop dispara replan automático.
    Plano novo gerado, missão continua.
    """
```

### 5.3 Testes de não-regressão

```python
# tests/regression/test_phase_6_still_works.py
def test_orchestrator_tier_classification_unchanged()
def test_subagent_isolation_unchanged()
def test_cron_persistence_unchanged()
```

---

## 6. Métricas a coletar (obrigatório, vai pro F11 Web UI)

```python
# agent/metrics/phase_7.py

METRICS = {
    "missions_active": Gauge,
    "missions_completed_24h": Counter,
    "missions_failed_24h": Counter,
    "missions_abandoned_24h": Counter,

    "steps_executed_per_tick": Histogram,
    "step_success_rate": Gauge,             # done / (done + failed)
    "avg_steps_per_mission": Gauge,
    "avg_mission_duration_hours": Gauge,

    "critic_evaluations_total": Counter,
    "critic_approve_rate": Gauge,
    "critic_reject_rate": Gauge,
    "critic_escalate_rate": Gauge,
    "critic_latency_p50_ms": Gauge,
    "critic_latency_p95_ms": Gauge,
    "critic_cost_usd_per_eval": Histogram,

    "reflexive_insights_total": Gauge,
    "reflexive_recall_count_24h": Counter,
    "reflexive_forgotten_count": Gauge,
}
```

**Alertas (loga warning no log estruturado, não vai pra prod ainda):**
- `critic_approve_rate > 0.95` por 24h → suspeita de critic capturado (rubber stamp). Investigar.
- `critic_reject_rate > 0.40` por 24h → crítico paranoico, planner ruim, ou tool irreversível mal classificada.
- `step_success_rate < 0.50` por 7d → planner está gerando passos inviáveis.

---

## 7. Anti-padrões (proibido)

Já marcados na memória, repetindo aqui pra ficar no spec:

1. **Sem vocabulário pomposo.** Nada de "atratores", "CACM", "autoDream", "KAIROS", "synapse". Componentes nomeados pelo que fazem: `MissionStore`, `Critic`, `AutonomousLoop`, `MissionReflector`. Já vimos isso falhar no `gaahzx/jarvis` e no EVE-Agent TS. Não repete.

2. **Sem self-commit loop.** O `AutonomousLoop` **não** chama LLM. Só despacha. Quem chama LLM é Planner/Critic/Reflector — todos com escopo bem definido e timeout duro. Loop em cima de loop em cima de LLM é como agente trava ou queima crédito.

3. **Sem geração massiva de pares sintéticos.** Reflexões viram memória reflexiva (poucas, escolhidas). Não geramos 10k pares pra fine-tune aqui. Isso é Fase 13 e só com benchmark externo.

4. **Sem critic capturado.** Personas rodam em paralelo, não sequencial. Sintetizador não pode ver os pareceres antes de gerar o seu — recebe os 3 prontos.

5. **Sem desabilitar critic via flag.** Pode-se ajustar threshold, mas não existe `--skip-critic` em prod. Em dev, sim, com warning gritante no log.

6. **Sem auto-promoção de tier baseado em "achismo".** Toda promoção pra Critic/Reflector tem regra explícita em `needs_critic()`. Se o agente decidir sozinho que algo "merece" critic sem cair na lista, a regra entra na lista. Mantemos a explicitude.

---

## 8. O que NÃO entra na Fase 7

- Sandboxes isolando subagente (Fase 8)
- Skills auto-geradas estilo Voyager (Fase 9)
- Deploy / supervisord / systemd (Fase 10)
- Web UI mostrando missões/critic logs (Fase 11)
- LoRA fine-tuning baseado em reflexões (Fase 13, depende de benchmark)

---

## 9. Critério de feito (Definition of Done)

A Fase 7 só está done quando, simultaneamente:

- [ ] Migration 007 aplicada e reversível (`agent db downgrade -1` funciona).
- [ ] `agent mission create` cria missão, mostra plano, pede confirmação.
- [ ] Loop dispara steps automaticamente (verificado em `agent loop status`).
- [ ] Missão sobrevive a `kill -9` do core e retoma após restart.
- [ ] Critic é chamado em pelo menos uma tool irreversível e o veredito vai pra `critic_evaluations`.
- [ ] Pelo menos um veredito `escalate` propaga pro Telegram da F5 e bloqueia execução.
- [ ] `MissionReflector` gera reflection com 4 campos e escreve em `reflexive_memory`.
- [ ] `agent memory reflexive search` retorna resultados.
- [ ] Métricas do §6 expostas em `/metrics` (Prometheus format), mesmo que UI ainda não consuma.
- [ ] Todos os testes do §5 passando em CI.
- [ ] Branch mergeada em `main`. Tag `phase-7-done`.
- [ ] `CLAUDE.md` atualizado.

Quando todos os checkboxes estiverem verdes, abre conversa nova e pede a Fase 8.
