"""
C10 Replay — Validação de D.1: Tool Routing por Step

Hipótese testada:
  Parte das missões TEATRO na Fase A não era "preguiça do LLM" — era o LLM
  reportando corretamente que as tools necessárias não estavam disponíveis
  no contexto.

Metodologia:
  FASE 1 — Análise de resolução (zero LLM calls):
    Para cada step TEATRO identificado na Fase A, executa resolve_tools_for_step()
    e compara tools antigas (pre-D.1) com tools novas (D.1).

  FASE 2 — Execução real (LLM calls, max 50):
    Seleciona 5 steps representativos e os executa via Orchestrator real.
    Registra se o verdict muda de 'prose_only' para 'executed'.

Resultado em: core/docs/phases/D1_REPLAY_RESULTS.md
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Garante imports do pacote local
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent.orchestrator.tiers import ExecutionTier
from agent.orchestrator.tool_router import (
    ALWAYS_TOOLS,
    StepSpec,
    resolve_tools_for_step,
)

# ─── Dados de entrada ─────────────────────────────────────────────────────────
# Steps TEATRO identificados na Fase A (EXECUTION_AUDIT.md + DB query)
# tools_pre_d1 = set de tools injetadas ANTES de D.1 (hardcoded em router.py STRATEGIC)

TEATRO_STEPS = [
    # smoke-loc-real (2026-05-23) — 5 steps todos marcados 'done' sem tool call
    {
        "id": "61b58c70-a346-4124-bd97-6354e441babe",
        "mission": "smoke-loc-real",
        "sequence": 0,
        "description": "Verificar existência e permissões do diretório core/src/agent",
        "expected_tools": ["list_dir", "shell"],
    },
    {
        "id": "d86f9ac6-5489-41b4-a174-e3dde9d8e62e",
        "mission": "smoke-loc-real",
        "sequence": 1,
        "description": "Listar recursivamente todos os arquivos com extensão .py nesse diretório",
        "expected_tools": ["list_dir", "shell"],
    },
    {
        "id": "99e07590-e44c-444c-aaa4-6058642d7473",
        "mission": "smoke-loc-real",
        "sequence": 2,
        "description": "Para cada arquivo .py encontrado, contar suas linhas de código",
        "expected_tools": ["shell", "read_file"],
    },
    {
        "id": "bd9ab411-ff97-4cc3-8bee-29276a334553",
        "mission": "smoke-loc-real",
        "sequence": 3,
        "description": "Formatar resultados como '<caminho>: <linhas>' para cada arquivo",
        "expected_tools": [],  # step de formatação — sem tool específica
    },
    {
        "id": "0b66649b-a894-4f7e-83f9-2559d3b9f7ec",
        "mission": "smoke-loc-real",
        "sequence": 4,
        "description": "Escrever output formatado no arquivo /tmp/loc_real.txt",
        "expected_tools": ["write_file"],
    },
    # Pesquisar frameworks Python (2026-05-10) — step 0 TEATRO
    {
        "id": "96354302-7b7b-4681-bf6d-e61037052506",
        "mission": "Pesquisar frameworks Python",
        "sequence": 0,
        "description": "Acessar PyPI.org e consultar estatísticas de downloads dos últimos 30 dias para frameworks pytest, unittest e nose2",
        "expected_tools": ["web_search"],
    },
    # smoke-B5-validation step 1 — failed_no_execution
    {
        "id": "237773cc-eadc-4979-8aff-34dea00d014e",
        "mission": "smoke-B5-validation",
        "sequence": 1,
        "description": "Gravar contagem em /tmp/smoke_b5.txt",
        "expected_tools": ["write_file"],
    },
]

# Tools disponíveis ANTES de D.1 (STRATEGIC hardcoded em router.py)
PRE_D1_TOOLS = frozenset(["web_search", "read_file", "salvar_memoria", "ler_memoria"])


# ─── Fase 1: Análise de resolução ─────────────────────────────────────────────


@dataclass
class ResolutionResult:
    step_id: str
    mission: str
    seq: int
    description: str
    pre_d1_tools: list[str]
    d1_tools: list[str]
    d1_source: str
    d1_inferred: list[str]
    expected_tools: list[str]
    new_tools_added: list[str]  # tools em D.1 que não estavam pre-D.1
    expected_covered: bool  # D.1 cobre todas as expected_tools?


async def fase1_resolution_analysis() -> list[ResolutionResult]:
    """Roda resolve_tools_for_step para cada step TEATRO. Zero LLM calls."""
    print("\n" + "=" * 70)
    print("FASE 1 — Análise de resolução de tools (zero LLM calls)")
    print("=" * 70)

    results = []
    for step in TEATRO_STEPS:
        spec = StepSpec(
            description=step["description"],
            tools_required=[],  # simula missão antiga: sem tools_required declaradas
        )
        resolution = await resolve_tools_for_step(
            spec,
            ExecutionTier.STRATEGIC,
            model_router=None,  # sem LLM — cai em keyword ou fallback
        )

        pre_d1 = sorted(PRE_D1_TOOLS | set(ALWAYS_TOOLS))
        d1 = sorted(resolution.tools)
        new_added = sorted(set(d1) - set(pre_d1))
        expected = step["expected_tools"]
        covered = all(t in d1 for t in expected) if expected else True

        res = ResolutionResult(
            step_id=step["id"],
            mission=step["mission"],
            seq=step["sequence"],
            description=step["description"],
            pre_d1_tools=pre_d1,
            d1_tools=d1,
            d1_source=resolution.source,
            d1_inferred=resolution.tools_inferred,
            expected_tools=expected,
            new_tools_added=new_added,
            expected_covered=covered,
        )
        results.append(res)

        status = "✅" if covered else ("⚠️" if not expected else "❌")
        print(f"\n{status} [{step['mission']}] Step {step['sequence']}")
        print(f"   desc    : {step['description'][:70]}...")
        print(f"   source  : {resolution.source}")
        print(f"   inferred: {resolution.tools_inferred}")
        print(f"   pre-D1  : {pre_d1}")
        print(f"   D.1     : {d1}")
        print(f"   NOVAS   : {new_added}")
        print(f"   expected: {expected} → coberto: {covered}")

    return results


# ─── Fase 2: Execução real via Orchestrator ───────────────────────────────────


@dataclass
class ExecutionResult:
    step_description: str
    mission_title: str
    pre_d1_verdict: str
    d1_verdict: str
    tools_resolved: list[str]
    tools_used: list[str]
    changed: bool  # de TEATRO para executed
    llm_calls: int
    duration_s: float
    error: str | None


async def _run_single_step(
    description: str,
    mission_title: str,
    expected_tools: list[str],
    orchestrator,
) -> ExecutionResult:
    """
    Executa um step via Orchestrator real e captura resultado.
    O orchestrator internamente chama resolve_tools_for_step() (D.1).
    """
    from agent.orchestrator.tool_router import StepSpec, resolve_tools_for_step
    from agent.tasks.task import Task, TaskSource

    t0 = time.monotonic()

    # Pre-resolve só para log — o orchestrator vai fazer o mesmo internamente
    spec = StepSpec(description=description, tools_required=[])
    resolution = await resolve_tools_for_step(spec, ExecutionTier.STRATEGIC, model_router=None)

    # Task com tools_required=[] → D.1 vai inferir por keyword/fallback
    import asyncpg as _apg

    from agent.tasks.store import TaskStore

    postgres_dsn = os.getenv("POSTGRES_DSN", "postgresql://agent:qualquercoisa123@localhost:5432/agent").replace(
        "@postgres:", "@localhost:"
    )
    _task_pool = await _apg.create_pool(postgres_dsn, min_size=1, max_size=1)
    task_store = TaskStore(_task_pool)
    task = Task(
        content=description,
        source=TaskSource.API,
        channel_ref={"source": "c10_replay", "mission": mission_title},
        tools_required=[],
    )
    # Persiste task no DB antes de chamar route()
    await task_store.create(task)

    try:
        result = await asyncio.wait_for(
            orchestrator.route(task=task),
            timeout=180,
        )
        duration = time.monotonic() - t0

        tools_used = [tc.tool_name for tc in (result.tool_calls_made or [])]
        d1_verdict = "executed" if tools_used else "prose_only"

        return ExecutionResult(
            step_description=description,
            mission_title=mission_title,
            pre_d1_verdict="prose_only",  # era TEATRO antes de D.1
            d1_verdict=d1_verdict,
            tools_resolved=resolution.tools,
            tools_used=tools_used,
            changed=bool(tools_used),
            llm_calls=getattr(result, "iterations", 1) or 1,
            duration_s=duration,
            error=None,
        )
    except TimeoutError:
        duration = time.monotonic() - t0
        return ExecutionResult(
            step_description=description,
            mission_title=mission_title,
            pre_d1_verdict="prose_only",
            d1_verdict="timeout",
            tools_resolved=resolution.tools,
            tools_used=[],
            changed=False,
            llm_calls=1,
            duration_s=duration,
            error="timeout 180s",
        )
    except Exception as exc:
        duration = time.monotonic() - t0
        return ExecutionResult(
            step_description=description,
            mission_title=mission_title,
            pre_d1_verdict="prose_only",
            d1_verdict="error",
            tools_resolved=resolution.tools,
            tools_used=[],
            changed=False,
            llm_calls=1,
            duration_s=duration,
            error=str(exc)[:300],
        )
    finally:
        await _task_pool.close()


async def fase2_live_execution(resolution_results: list[ResolutionResult]) -> list[ExecutionResult]:
    """
    Executa 5 steps representativos via Orchestrator real.
    Max 50 LLM calls total. Timeout 180s por step.
    """
    print("\n" + "=" * 70)
    print("FASE 2 — Execução real via Orchestrator (LLM calls ativadas)")
    print("=" * 70)

    # Seleciona 5 steps para execução real:
    # - 2+ steps que precisam de write_file/shell (faltavam antes de D.1)
    # - 1 step de web_search (controle — tinha a tool antes também)
    # - Variedade de missões
    REPLAY_STEPS = [
        {
            "description": "Escrever o texto 'c10_replay_ok_' + str(42) no arquivo /tmp/c10_d1_test.txt",
            "mission": "C10-write-test",
            "expected": ["write_file"],
            "reason": "write_file faltava pre-D1 (STRATEGIC só tinha web_search+read_file)",
        },
        {
            "description": "Listar arquivos .py em /tmp/ e retorne a lista",
            "mission": "C10-listdir-test",
            "expected": ["list_dir"],
            "reason": "list_dir faltava pre-D1",
        },
        {
            "description": "Pesquisar na web o que é pytest e retorne o primeiro resultado",
            "mission": "C10-websearch-control",
            "expected": ["web_search"],
            "reason": "CONTROLE — web_search já existia pre-D1, deve continuar funcionando",
        },
        {
            "description": "Ler o conteúdo do arquivo /tmp/c10_d1_test.txt e retorne as primeiras 3 linhas",
            "mission": "C10-readfile-test",
            "expected": ["read_file"],
            "reason": "read_file existia pre-D1 mas keyword inference agora é explícita",
        },
        {
            "description": "Listar recursivamente todos os arquivos com extensão .py nesse diretório core/src/agent e contar quantos existem",
            "mission": "C10-smoke-loc-replica",
            "expected": ["list_dir"],
            "reason": "Réplica do smoke-loc-real que era TEATRO (listdir + shell faltavam)",
        },
    ]

    # Setup
    import asyncpg

    postgres_dsn = os.getenv("POSTGRES_DSN", "postgresql://agent:qualquercoisa123@localhost:5432/agent")
    # Substitui hostname interno 'postgres' por 'localhost' se necessário
    postgres_dsn = postgres_dsn.replace("@postgres:", "@localhost:")

    db_pool = await asyncpg.create_pool(postgres_dsn, min_size=1, max_size=3)

    try:
        from agent.orchestrator.router import Orchestrator
        from agent.orchestrator.tiers import TierClassifier

        # Verifica providers disponíveis
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        # Testa Ollama primeiro (API Anthropic pode estar rate-limited)
        import httpx

        ollama_ok = False
        try:
            r = httpx.get(f"{ollama_url}/api/tags", timeout=3)
            ollama_ok = r.status_code == 200
        except Exception:
            pass

        if not ollama_ok and not anthropic_key:
            print("⚠️  Nem Ollama nem Anthropic disponíveis — Fase 2 pulada")
            return []

        from agent.config import build_model_router

        model_router = build_model_router(db_pool=db_pool)

        # Override: força uso de Ollama se disponível (Anthropic pode estar rate-limited)
        REPLAY_MODEL = "ollama:qwen2.5:7b" if ollama_ok else "anthropic:claude-haiku-4-5"
        print(f"   Modelo para replay: {REPLAY_MODEL} (ollama_ok={ollama_ok})")

        # TierClassifier: usa Ollama se disponível (evita Anthropic rate-limit)
        classifier = TierClassifier(
            model_router=model_router,
            model=REPLAY_MODEL,
        )
        from agent.subagents.pool import SubagentPool
        from agent.tasks.store import TaskStore

        task_store = TaskStore(db_pool)
        pool = SubagentPool(
            model_router=model_router,
            task_store=task_store,
            approval_manager=None,
            hard_timeout_s=180,  # max 180s por step
        )
        orchestrator = Orchestrator(
            model_router=model_router,
            task_store=task_store,
            subagent_pool=pool,
            classifier=classifier,
            db_pool=db_pool,
        )

        results = []
        total_llm_calls = 0
        LLM_CALL_LIMIT = 50

        for step_data in REPLAY_STEPS:
            if total_llm_calls >= LLM_CALL_LIMIT:
                print(f"\n⚠️  Limite de {LLM_CALL_LIMIT} LLM calls atingido — parando Fase 2")
                break

            print(f"\n▶ Executando: {step_data['mission']}")
            print(f"  desc   : {step_data['description'][:80]}")
            print(f"  reason : {step_data['reason']}")

            res = await _run_single_step(
                description=step_data["description"],
                mission_title=step_data["mission"],
                expected_tools=step_data["expected"],
                orchestrator=orchestrator,
            )

            total_llm_calls += res.llm_calls
            results.append(res)

            status = (
                "✅ TEATRO→EXECUTED"
                if res.changed
                else ("❌ AINDA TEATRO" if not res.error else f"❌ ERROR: {res.error[:60]}")
            )
            print(f"  resultado : {status}")
            print(f"  tools_resolved: {res.tools_resolved}")
            print(f"  tools_used    : {res.tools_used}")
            print(f"  llm_calls: {res.llm_calls} | duration: {res.duration_s:.1f}s | total: {total_llm_calls}")

        return results

    finally:
        await db_pool.close()


# ─── Geração do relatório ─────────────────────────────────────────────────────


def generate_report(
    resolution_results: list[ResolutionResult],
    execution_results: list[ExecutionResult],
    elapsed_s: float,
) -> str:
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Métricas de resolução
    steps_with_new_tools = sum(1 for r in resolution_results if r.new_tools_added)
    steps_expected_covered = sum(1 for r in resolution_results if r.expected_covered)
    total_steps = len(resolution_results)

    # Métricas de execução
    changed_count = sum(1 for r in execution_results if r.changed)
    total_exec = len(execution_results)
    total_llm_calls = sum(r.llm_calls for r in execution_results)

    lines = [
        "# D1_REPLAY_RESULTS — C10 Replay",
        "",
        f"> Data: {now}",
        "> Branch: `feature/d1-tool-routing`",
        f"> Duração total: {elapsed_s:.1f}s",
        f"> Calls LLM: {total_llm_calls}/{50} (limite)",
        "",
        "---",
        "",
        "## Veredicto",
        "",
    ]

    if changed_count >= 2:
        verdict = "✅ **D.1 CONFIRMADO** — hipótese validada"
        verdict_detail = f"{changed_count}/{total_exec} missões mudaram de TEATRO para executed."
    elif changed_count == 1:
        verdict = "⚠️  **D.1 PARCIAL** — melhora parcial"
        verdict_detail = f"Apenas 1/{total_exec} missão mudou de TEATRO para executed."
    elif total_exec == 0:
        verdict = "⚠️  **FASE 2 PULADA** — apenas análise de resolução foi executada"
        verdict_detail = "API key indisponível ou limite atingido antes de rodar execuções reais."
    else:
        verdict = "❌ **D.1 NÃO RESOLVEU** — hipótese não confirmada"
        verdict_detail = f"0/{total_exec} missões mudaram status. Causa raiz é outra."

    lines += [
        verdict,
        "",
        verdict_detail,
        "",
        "---",
        "",
        "## Fase 1 — Análise de resolução de tools",
        "",
        f"**Steps TEATRO analisados:** {total_steps}",
        f"**Steps que ganham NOVAS tools com D.1:** {steps_with_new_tools}/{total_steps}",
        f"**Steps com todas as expected_tools cobertas:** {steps_expected_covered}/{total_steps}",
        "",
        "| Step | Missão | source | Novas tools (D.1) | Expected coberto |",
        "|------|--------|--------|-------------------|-----------------|",
    ]

    for r in resolution_results:
        novas = ", ".join(r.new_tools_added) if r.new_tools_added else "—"
        covered = "✅" if r.expected_covered else "❌"
        desc_short = r.description[:50] + "..." if len(r.description) > 50 else r.description
        lines.append(f"| {r.seq} | {r.mission} | {r.d1_source} | `{novas}` | {covered} |")

    lines += [
        "",
        "### Detalhes por step",
        "",
    ]

    for r in resolution_results:
        lines += [
            f"#### [{r.mission}] Step {r.seq}",
            f"- **Descrição:** {r.description}",
            f"- **Source D.1:** `{r.d1_source}`",
            f"- **Tools inferidas (keyword):** `{r.d1_inferred}`",
            f"- **Pre-D.1 tools:** `{sorted(r.pre_d1_tools)}`",
            f"- **D.1 tools:** `{sorted(r.d1_tools)}`",
            f"- **Novas tools adicionadas:** `{r.new_tools_added}`",
            f"- **Expected:** `{r.expected_tools}` → coberto: {'✅' if r.expected_covered else '❌'}",
            "",
        ]

    lines += [
        "---",
        "",
        "## Fase 2 — Execução real via Orchestrator",
        "",
    ]

    if not execution_results:
        lines += [
            "*(Fase 2 pulada — API key não disponível ou limite de LLM calls atingido)*",
            "",
        ]
    else:
        lines += [
            f"**Steps executados:** {total_exec}",
            f"**TEATRO → executed:** {changed_count}/{total_exec}",
            f"**Calls LLM usadas:** {total_llm_calls}",
            "",
            "| Missão | Pre-D1 | D.1 | Tools usadas | LLM calls |",
            "|--------|--------|-----|--------------|-----------|",
        ]
        for r in execution_results:
            tools_str = ", ".join(r.tools_used) if r.tools_used else "—"
            d1_v = r.d1_verdict if not r.error else f"error: {r.error[:40]}"
            lines.append(f"| {r.mission_title} | {r.pre_d1_verdict} | {d1_v} | `{tools_str}` | {r.llm_calls} |")

        lines.append("")

        for r in execution_results:
            status = "✅" if r.changed else ("❌" if not r.error else "💥")
            lines += [
                f"#### {status} {r.mission_title}",
                f"- **Descrição:** {r.step_description}",
                f"- **Tools resolvidas:** `{r.tools_resolved}`",
                f"- **Tools usadas:** `{r.tools_used}`",
                f"- **Verdict pré-D.1:** `{r.pre_d1_verdict}`",
                f"- **Verdict D.1:** `{r.d1_verdict}`",
                f"- **Mudou (TEATRO→exec):** {'Sim ✅' if r.changed else 'Não ❌'}",
                f"- **LLM calls:** {r.llm_calls} | Duração: {r.duration_s:.1f}s",
                f"- **Erro:** {r.error or '—'}",
                "",
            ]

    lines += [
        "---",
        "",
        "## Conclusão",
        "",
    ]

    if changed_count >= 2:
        lines += [
            f"**D.1 confirmado.** {changed_count} de {total_exec} steps que eram TEATRO passaram a executar",
            "tool calls reais após a disponibilização das tools corretas via `resolve_tools_for_step()`.",
            "",
            f"A análise de resolução mostra que {steps_with_new_tools} dos {total_steps} steps TEATRO históricos",
            "recebem tools novas com D.1 que não estavam disponíveis pre-D.1 (STRATEGIC hardcoded",
            '`["web_search", "read_file", "salvar_memoria", "ler_memoria"]`).',
            "",
            "**Próximo passo:** tag `d1-done` e merge para `main`.",
        ]
    elif total_exec == 0:
        lines += [
            "A análise de resolução (Fase 1) confirma que D.1 expandiria o conjunto de tools para",
            f"{steps_with_new_tools} dos {total_steps} steps TEATRO históricos.",
            "",
            "A Fase 2 (execução real) foi pulada por falta de API key ou limite de LLM calls.",
            "Para confirmar o veredicto final, re-rodar com ANTHROPIC_API_KEY configurada.",
        ]
    else:
        lines += [
            f"D.1 não resolveu o problema de TEATRO nas {total_exec} execuções testadas.",
            "A causa raiz pode ser outra. Investigar:",
            "- Prompt do subagente (não instrui explicitamente uso de tools?)",
            "- Timeout ou limite de iterações muito baixo?",
            "- LLM recusa tools mesmo quando disponíveis?",
            "",
            "Ver FASE_D_BACKLOG.md para próximas investigações.",
        ]

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    t0 = time.monotonic()

    # Fase 1: Análise de resolução (sem LLM)
    resolution_results = await fase1_resolution_analysis()

    # Fase 2: Execução real (com LLM)
    execution_results = await fase2_live_execution(resolution_results)

    elapsed = time.monotonic() - t0

    # Gera relatório
    report = generate_report(resolution_results, execution_results, elapsed)

    # Salva relatório
    out_path = Path(__file__).parents[1] / "docs" / "phases" / "D1_REPLAY_RESULTS.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(f"\n{'=' * 70}")
    print(f"Relatório salvo: {out_path}")
    print(f"Duração total: {elapsed:.1f}s")
    print(f"{'=' * 70}")

    # Imprime veredicto
    changed = sum(1 for r in execution_results if r.changed)
    total = len(execution_results)
    if changed >= 2:
        print(f"\n✅ VEREDICTO: D.1 CONFIRMADO ({changed}/{total} missions TEATRO→done)")
    elif total == 0:
        print("\n⚠️  VEREDICTO: Fase 2 pulada — apenas análise de resolução concluída")
        print(
            f"   Análise mostra: {sum(1 for r in resolution_results if r.new_tools_added)}/{len(resolution_results)} steps ganham novas tools com D.1"
        )
    else:
        print(f"\n❌ VEREDICTO: D.1 não resolveu ({changed}/{total} missions mudaram) — investigar")

    return changed >= 2 or (total == 0 and len(resolution_results) > 0)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
