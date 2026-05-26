# Fase 9 — Skills Auto-Geradas (Voyager-style)

**Status anterior:** F8 (Sandboxes) concluída — toda execução arbitrária passa por `DockerSandbox`/`SubprocessSandbox` com política e limites duros, lint do Orchestrator garante `exec_tool` como ponto único.
**Objetivo F9:** O agente passa a **criar suas próprias skills** a partir de padrões repetidos de execução. Cada skill é um artefato versionado, testado em sandbox `SKILL_DEV`, com manifesto declarativo, e indexada para busca semântica antes da próxima execução. Inspiração no Voyager (Wang et al.), mas sem mística — é detecção de padrão + síntese de código + validação dura.

---

## 1. Princípios

- **Skill é arquivo, não memória difusa.** Cada skill vira `skills/<slug>/skill.py` + `skills/<slug>/manifest.yaml` no repo do agente, commitável e versionável.
- **Auto-criação tem gatilho explícito.** Skill só é proposta quando há ≥5 execuções similares bem-sucedidas (cosine ≥0.85 nas descrições) E ganho de tempo médio justifica (≥30%). Sem mass-generation.
- **Toda skill nasce em sandbox `SKILL_DEV`.** Manifesto obrigatório com `network_policy`, `sandbox_profile`, `irreversible`, `inputs_schema`, `outputs_schema`. Sem isso, rejeita.
- **Validação dura antes de publicar.** Cada skill precisa passar: lint (ruff), 2+ testes auto-gerados pelo agente que rodam em sandbox, smoke run com input sintético. Falhou → vai pra `skills/_rejected/` com motivo.
- **Crítico decide promoção.** Skill candidata vai pro Conclave (3 personas da F7) antes de ser ativada. Sem aprovação do Crítico, fica em `skills/_pending/`.
- **Busca semântica antes de gerar.** Toda nova execução checa skills existentes primeiro (embedding match ≥0.78). Reuso > regeneração.
- **Decay de skills inúteis.** Skill sem uso em 30 dias OU com taxa de erro >40% nas últimas 10 execuções é marcada `deprecated` e movida pra `skills/_archive/`.
- **Anti-pomposidade.** Nomes técnicos: `SkillRegistry`, `SkillSynthesizer`, `SkillValidator`. Sem "Voyager", "Genesis", "Atlas".

---

## 2. Arquitetura

```
agent/
  skills/
    __init__.py
    registry.py            # SkillRegistry: load/save/search/promote/deprecate
    manifest.py            # SkillManifest (Pydantic), validação de schema
    synthesizer.py         # SkillSynthesizer: detecta padrão + gera código via LLM
    validator.py           # SkillValidator: lint + testes + smoke em sandbox
    embeddings.py          # SkillEmbedder: indexa skills no banco vetorial (sqlite-vss ou chromadb)
    decay.py               # SkillDecayManager: marca deprecated, arquiva
    promoter.py            # SkillPromoter: integra com Crítico (F7)
    runner.py              # SkillRunner: executa skill via sandbox (F8)
    exceptions.py          # SkillValidationFailed, SkillNotFound, etc.
  storage/
    migrations/
      009_skills.sql       # tabela skills, skill_executions, skill_candidates
  cli/
    skills_cmd.py          # agent skills list/show/run/promote/reject/archive
repo_root/
  skills/                  # NÃO confundir com agent/skills/ — este é o "userland"
    _active/               # skills ativas, prontas pra uso
    _pending/              # candidatas aguardando Crítico
    _rejected/             # falharam validação (com motivo no manifesto)
    _archive/              # deprecadas
    <slug>/
      skill.py             # função pública async def run(input: dict) -> dict
      manifest.yaml
      tests/
        test_smoke.py
```

---

## 3. SkillManifest (formato YAML)

```yaml
slug: extract_youtube_transcript
version: 1
created_at: 2026-05-10T14:30:00Z
created_by: synthesizer
description: "Extrai transcrição de vídeo do YouTube dado um URL."
embedding_text: "youtube transcript download captions extraction video url"

inputs_schema:
  type: object
  properties:
    url: { type: string, format: uri }
    language: { type: string, default: "pt" }
  required: [url]

outputs_schema:
  type: object
  properties:
    transcript: { type: string }
    duration_seconds: { type: number }
  required: [transcript]

sandbox_profile: SKILL_DEV   # ou DEFAULT, UNTRUSTED
network_policy:
  allow_domains:
    - youtube.com
    - youtubei.googleapis.com
irreversible: false
estimated_wall_time_seconds: 30
estimated_memory_mb: 256

stats:
  executions: 0
  successes: 0
  failures: 0
  last_used_at: null
  avg_duration_seconds: null

provenance:
  pattern_source_executions: [exec_id_1, exec_id_2, ...]  # quais execuções geraram
  synthesized_from_template: ad_hoc
  critic_approval_id: critic_decision_42
```

Manifesto inválido (faltando `inputs_schema`, `sandbox_profile`, etc.) → skill rejeitada automaticamente.

---

## 4. SkillSynthesizer — fluxo de geração

1. **Trigger.** `SkillDecayManager` ou hook pós-execução chama `SkillSynthesizer.scan_for_candidates()`.
2. **Detecção de padrão.** Query no `execution_traces` (F6+F8): busca grupos de execuções com:
   - `success=True`
   - mesma família de tool (`exec_tool` com comandos similares)
   - descrição/intent com cosine ≥0.85
   - ≥5 ocorrências nos últimos 14 dias
3. **Análise.** Pra cada cluster, extrai: comando comum, variáveis (URLs, paths, etc.), tempo médio, domínios de rede usados.
4. **Síntese.** Manda pro LLM um prompt estruturado com: amostras das execuções, schema desejado, template de skill. LLM retorna `skill.py` + `manifest.yaml`.
5. **Validação local.** `SkillValidator.validate(candidate)`:
   - ruff check (zero erros)
   - manifesto parse + schema check
   - tipo das funções (assinatura `async def run(input: dict) -> dict`)
   - 2 testes auto-gerados rodam em sandbox SKILL_DEV → ambos verdes
   - smoke run com input sintético → output bate com `outputs_schema`
6. **Promoção.** Se passou tudo, vai pra `skills/_pending/<slug>/` e o `SkillPromoter` enfileira no Crítico (F7).
7. **Aprovação.** Crítico aprovou → move pra `skills/_active/`, indexa embedding, evento `skill.promoted` emitido.

Se falhou em qualquer etapa → `skills/_rejected/<slug>/` com `reason.txt`. Sem retry automático (decisão dura: regenerar é responsabilidade de uma futura execução, não de loop).

---

## 5. SkillRunner — execução

```python
async def run_skill(slug: str, input: dict, *, mission_id: str | None = None) -> SkillResult:
    skill = registry.get(slug)
    if skill.status != "active":
        raise SkillNotActive(slug)

    # valida input contra schema
    validate_input(input, skill.manifest.inputs_schema)

    # monta SandboxPolicy do manifesto
    policy = SandboxPolicy(
        profile=skill.manifest.sandbox_profile,
        network=NetworkPolicy(allow_domains=skill.manifest.network_policy.allow_domains),
        wall_time_seconds=skill.manifest.estimated_wall_time_seconds * 3,  # margem 3x
        memory_mb=skill.manifest.estimated_memory_mb * 2,
    )

    # executa via exec_tool da F8 (single entry point)
    result = await exec_tool(
        command=["python", "-m", "skill_runtime", skill.slug],
        files={"input.json": json.dumps(input).encode()},
        policy=policy,
        labels={"skill_slug": slug, "mission_id": mission_id},
    )

    # parse output, valida contra schema
    output = json.loads(result.stdout)
    validate_output(output, skill.manifest.outputs_schema)

    # atualiza stats da skill (executions++, successes/failures, avg_duration)
    registry.record_execution(slug, success=True, duration=result.duration)

    return SkillResult(slug=slug, output=output, sandbox_result=result)
```

- **Single entry point:** toda execução de skill passa por `exec_tool` da F8. Sem bypass.
- **Stats atualizadas em tempo real.** Decay manager lê daí.
- **mission_id propagado** pra rastrear no trace consolidado.

---

## 6. Busca antes de gerar

Antes de qualquer execução nova do Orchestrator que envolva `exec_tool` com comando não-trivial, o flow é:

1. `SkillRegistry.search(intent_embedding, top_k=3)` → retorna skills com cosine ≥0.78
2. Se houver match: Orchestrator tenta `SkillRunner.run_skill(match.slug, input)` em vez de gerar comando novo
3. Se skill match falhar (erro de schema, exceção em runtime): degrada pra `exec_tool` direto, registra `skill.fallback_to_exec` no trace
4. Se não houver match: execução normal, e a execução fica disponível pro `SkillSynthesizer` na próxima varredura

Embedding usado: mesmo que o da memória semântica (F5/F7) — `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

---

## 7. Decay e governança

`SkillDecayManager.scan()` roda no scheduler (APScheduler da F6) toda noite:

- Skill ativa sem execução em 30 dias → `deprecated`, move pra `_archive/`
- Skill com >40% de erro nas últimas 10 execuções → `flagged_for_review`, gera item no Crítico
- Skill com `version=1` aprovada há ≥7 dias e ≥20 execuções bem-sucedidas → `mature` (sinaliza estabilidade, libera uso por subagentes sem reaprovação)

Tudo registrado em eventos: `skill.deprecated`, `skill.flagged`, `skill.matured`.

---

## 8. CLI

```
agent skills list [--status=active|pending|rejected|archive]
agent skills show <slug>
agent skills run <slug> --input='{"url":"..."}'
agent skills promote <slug>                # força promoção (requer flag --force se Crítico rejeitou)
agent skills reject <slug> --reason="..."
agent skills archive <slug>
agent skills synthesize --scan             # roda SkillSynthesizer.scan_for_candidates() manualmente
agent skills stats                         # tabela: slug, status, executions, success_rate, last_used
```

Todos os comandos batem na API HTTP (`/api/v1/skills/*`), nada de SQL direto via CLI.

---

## 9. Integrações com fases anteriores

- **F5 (memória):** embedding de skill usa o mesmo modelo da memória semântica. Reuso de infra vetorial.
- **F6 (orchestrator + scheduler):** `SkillDecayManager` é uma job recorrente do APScheduler. `SkillRunner` é chamado pelo Orchestrator antes de gerar `exec_tool` direto.
- **F7 (Crítico + Missões):** toda skill candidata passa pelo Conclave. Missões podem requisitar skills específicas por slug.
- **F8 (Sandbox):** `SkillRunner` é wrapper sobre `exec_tool`. Profile `SKILL_DEV` usado pra validação de candidatas, `DEFAULT` pra skills maduras, `UNTRUSTED` se manifesto pedir.

---

## 10. Persistência

Migration `009_skills.sql`:

```sql
CREATE TABLE skills (
  slug TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK (status IN ('pending','active','rejected','deprecated','flagged_for_review','mature')),
  manifest_json TEXT NOT NULL,
  embedding BLOB,                    -- vector serializado
  created_at TIMESTAMP NOT NULL,
  promoted_at TIMESTAMP,
  last_used_at TIMESTAMP,
  executions_count INTEGER DEFAULT 0,
  successes_count INTEGER DEFAULT 0,
  failures_count INTEGER DEFAULT 0,
  avg_duration_seconds REAL,
  critic_approval_id TEXT,
  rejection_reason TEXT
);

CREATE TABLE skill_executions (
  id TEXT PRIMARY KEY,
  skill_slug TEXT NOT NULL REFERENCES skills(slug),
  sandbox_execution_id TEXT REFERENCES sandbox_executions(id),
  mission_id TEXT,
  input_json TEXT NOT NULL,
  output_json TEXT,
  success BOOLEAN NOT NULL,
  duration_seconds REAL NOT NULL,
  error_message TEXT,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE skill_candidates (
  id TEXT PRIMARY KEY,
  proposed_slug TEXT NOT NULL,
  source_execution_ids TEXT NOT NULL,  -- JSON array
  pattern_cluster_score REAL NOT NULL,
  llm_synthesis_prompt TEXT,
  llm_synthesis_response TEXT,
  validation_report_json TEXT,
  status TEXT NOT NULL CHECK (status IN ('synthesizing','validating','approved','rejected')),
  created_at TIMESTAMP NOT NULL,
  resolved_at TIMESTAMP
);

CREATE INDEX idx_skills_status ON skills(status);
CREATE INDEX idx_skill_executions_slug ON skill_executions(skill_slug, created_at DESC);
```

---

## 11. Eventos

Novos eventos registrados em `event_registry`:

- `skill.candidate_detected` — payload: cluster_id, source_executions, score
- `skill.synthesized` — payload: slug, candidate_id
- `skill.validation_passed` / `skill.validation_failed` — payload: slug, report
- `skill.promoted` / `skill.rejected` — payload: slug, critic_approval_id
- `skill.executed` — payload: slug, success, duration
- `skill.fallback_to_exec` — payload: slug, reason
- `skill.deprecated` / `skill.flagged` / `skill.matured` — payload: slug, reason

---

## 12. Critérios de aceitação (10)

1. **C1 — Detecção:** dado 5+ execuções similares bem-sucedidas em `execution_traces`, `SkillSynthesizer.scan_for_candidates()` retorna ≥1 candidato com `pattern_cluster_score ≥0.85`.
2. **C2 — Manifesto obrigatório:** skill candidata sem `inputs_schema`, `outputs_schema`, `sandbox_profile` ou `network_policy` é rejeitada automaticamente com motivo no `rejection_reason`.
3. **C3 — Validação em sandbox:** `SkillValidator.validate()` roda lint + 2 testes + smoke run dentro de `SKILL_DEV` sandbox. Se qualquer etapa falha → candidata vai pra `_rejected/`.
4. **C4 — Crítico promove:** skill candidata aprovada localmente vai pro Conclave (F7); só vira `status=active` após aprovação do Crítico, com `critic_approval_id` preenchido.
5. **C5 — Busca antes de gerar:** Orchestrator com intent que faz match (cosine ≥0.78) com skill ativa usa `SkillRunner.run_skill()` em vez de `exec_tool` direto. Trace registra `skill_slug_used`.
6. **C6 — Fallback:** se `SkillRunner` falha (schema mismatch, exceção), Orchestrator degrada pra `exec_tool` e emite evento `skill.fallback_to_exec`.
7. **C7 — Single entry point:** `SkillRunner` SEMPRE chama `exec_tool` da F8. Lint do Orchestrator (extensão da F8) bloqueia chamada direta de `subprocess` em qualquer arquivo de `agent/skills/`.
8. **C8 — Decay:** `SkillDecayManager.scan()` marca como `deprecated` skills sem uso há ≥30 dias (data mockada nos testes). Skills com >40% erro nas últimas 10 execuções viram `flagged_for_review` e geram item no Crítico.
9. **C9 — CLI funcional:** `agent skills list`, `show`, `run`, `promote`, `reject`, `archive`, `stats`, `synthesize --scan` operam via API HTTP (`curl /api/v1/skills/*` retorna 200 nos casos felizes).
10. **C10 — Persistência e eventos:** todas as transições de estado (synthesized, validation_passed, promoted, executed, deprecated) criam linha em `skills`/`skill_executions`/`skill_candidates` E emitem evento correspondente em `event_registry`.

---

## 13. Fora de escopo (NÃO fazer na F9)

- **Edição de skill em runtime** (versionamento v2, v3): adiar pra F9.1 se necessário, mas v1 fica imutável depois de promovida.
- **Composição de skills** (skill que chama outra skill): só na F10+ depois que a base for sólida.
- **Marketplace/import de skills externas:** zero. Skills são geradas localmente do trace, ponto.
- **Fine-tuning baseado em skills:** isso é F13. Aqui só geramos artefatos versionados.
- **UI web pras skills:** F11. Aqui só CLI + API.

---

## 14. Anti-padrões explicitamente proibidos

- ❌ Gerar skill sem trigger (mass-synthesis especulativa)
- ❌ Pular o Crítico em skills auto-geradas
- ❌ Skill chamando `subprocess` direto, fora do `exec_tool`
- ❌ Network policy `OPEN` em skill sintetizada (precisa de allowlist explícita)
- ❌ Vocabulário pomposo: `VoyagerEngine`, `GenesisSkill`, `AtlasRegistry`, `SkillForge`
- ❌ Retry automático de skill rejeitada (uma vez rejected, fica rejected até intervenção)
- ❌ Auto-commit de skills geradas (proposta vai pra branch separada `feature/skill-<slug>`, humano revisa)

---

## 15. Entregáveis

- Branch `feature/phase-9-skills`
- Tag `phase-9-done` quando 10 critérios passarem
- Suite de testes: `tests/skills/` cobrindo cada um dos 10 critérios
- Smoke E2E via CLI + API HTTP (não só Python local)
- Migration `009_skills.sql` aplicada e idempotente
- Commit final com mensagem `feat(skills): F9 - Voyager-style auto-generated skills`
- Nenhuma dependência nova além de: `sqlite-vss` OU `chromadb` (escolher uma, justificar). `pyyaml` se ainda não estiver.
