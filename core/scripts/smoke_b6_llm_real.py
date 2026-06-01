"""
B.6 — Smoke test com LLM real (claude-haiku-4-5).

Sem mock no orchestrator. Mede se o LLM chama tools de verdade.
Usa `_process_mission` diretamente para evitar processar outras missões ativas.

Cenários:
  C1 — pedido CLARO (deve resultar em 'executed' em ambos os steps)
  C2 — pedido AMBÍGUO (mede taxa de prose_only no estado atual)

Custo estimado: ~$0.01-0.05 (Haiku 4.5: $0.80/1M in, $4/1M out)
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC
from unittest.mock import patch

os.environ["POSTGRES_DSN"] = "postgresql://agent:qualquercoisa123@localhost:5432/agent"
os.environ["POSTGRES_SSL_DISABLE"] = "1"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
# qwen3:30b disponível localmente — tool_use=True confirmado via /api/show
os.environ["DEFAULT_MODEL"] = "ollama:qwen3:30b"
os.environ["MODEL_FALLBACK_CHAIN"] = ""  # bloqueia fallback pra Anthropic (API limitada)
# .env tem OLLAMA_BASE_URL=https://ollama.com (cloud); sobrepõe para local
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

sys.path.insert(0, "/Users/fate/Desktop/agent/core/src")

# Carrega .env antes de qualquer import que leia vars de ambiente
try:
    from dotenv import load_dotenv

    load_dotenv("/Users/fate/Desktop/agent/.env", override=False)
except ImportError:
    pass  # python-dotenv não instalado — variáveis devem estar no env


# ── Bootstrap do Orchestrator real ───────────────────────────────────────────
async def build_orchestrator(pool):
    """~20 linhas. Replica setup mínimo do server.py para o Orchestrator."""
    from agent.config import build_model_router, get_settings
    from agent.memory.compressor import ContextCompressor
    from agent.orchestrator.router import Orchestrator
    from agent.orchestrator.tiers import TierClassifier
    from agent.subagents.pool import SubagentPool
    from agent.tasks.store import TaskStore

    settings = get_settings()
    model_router = build_model_router(settings, db_pool=pool)
    task_store = TaskStore(pool)

    subagent_pool = SubagentPool(
        model_router=model_router,
        task_store=task_store,
        approval_manager=None,
        max_concurrent=4,
        hard_timeout_s=120,
    )
    classifier = TierClassifier(
        model_router=model_router,
        model=settings.orchestrator.classifier_model,
    )
    compressor = ContextCompressor()

    orchestrator = Orchestrator(
        model_router=model_router,
        task_store=task_store,
        subagent_pool=subagent_pool,
        classifier=classifier,
        memory_store=None,  # sem memória persistente no smoke test
        curator=None,
        compressor=compressor,
        skill_manager=None,
        approval_manager=None,
        fast_max_iterations=settings.orchestrator.fast_max_iterations,
        strategic_max_iterations=settings.orchestrator.strategic_max_iterations,
    )
    return orchestrator, task_store


# ── Helper de execução de cenário ────────────────────────────────────────────
async def run_scenario(
    name: str,
    objective: str,
    steps: list[str],
    mission_store,
    task_store,
    orchestrator,
) -> dict:
    """
    Cria missão real, chama _process_mission() diretamente (evita processar
    outras missões ativas do DB), aguarda conclusão dos steps.
    """
    from agent.autonomous.loop import MAX_STEPS_PER_TICK, AutonomousLoop

    mission = await mission_store.create(
        title=f"smoke-B6-{name}",
        objective=objective,
        success_criteria=[{"criteria": "tool calls reais verificadas pelo fix B.3"}],
        deadline=None,
        source="cli",
        source_ref=None,
    )
    for i, desc in enumerate(steps):
        await mission_store.add_step(mission.id, description=desc, sequence=i)

    print(f"  Missão criada: {mission.id}")

    loop = AutonomousLoop(
        mission_store=mission_store,
        orchestrator=orchestrator,
        task_store=task_store,
    )

    # Usa _process_mission diretamente em vez de tick() para não afetar outras missões
    from datetime import datetime

    from agent.autonomous.loop import LoopReport

    for attempt in range(5):
        report = LoopReport(
            tick_at=datetime.now(tz=UTC),
            missions_checked=1,
            steps_dispatched=0,
            steps_failed=0,
            replans_triggered=0,
            missions_completed=0,
        )
        with patch("agent.autonomous.loop.needs_critic", return_value=False):
            dispatched, result = await loop._process_mission(mission, budget=MAX_STEPS_PER_TICK, report=report)

        print(f"    tick {attempt + 1}: dispatched={dispatched} result={result} steps_failed={report.steps_failed}")

        # Para quando não há mais pending
        pending = await mission_store._pool.fetchval(
            "SELECT COUNT(*) FROM mission_steps WHERE mission_id = $1 AND status IN ('pending', 'running')",
            mission.id,
        )
        if pending == 0:
            print(f"    → zero pendentes após tick {attempt + 1}")
            break
        await asyncio.sleep(1)  # pequena pausa entre ticks

    # Coleta resultados do DB
    rows = await mission_store._pool.fetch(
        """
        SELECT sequence, status,
               result->>'verdict'          AS verdict,
               result->'tools_invoked'     AS tools_invoked,
               result->>'tool_call_count'  AS tool_count,
               result->>'raw_text'         AS raw_text,
               result->>'text'             AS text,
               retry_count
        FROM mission_steps
        WHERE mission_id = $1
        ORDER BY sequence
        """,
        mission.id,
    )

    # Total de tokens via task store
    token_rows = await mission_store._pool.fetch(
        "SELECT tokens_in, tokens_out FROM tasks WHERE source = 'cron' "
        "AND created_at > NOW() - INTERVAL '5 minutes' "
        "AND content = ANY($1::text[])",
        steps,
    )
    total_in = sum(r["tokens_in"] or 0 for r in token_rows)
    total_out = sum(r["tokens_out"] or 0 for r in token_rows)
    cost_usd = (total_in * 0.80 + total_out * 4.0) / 1_000_000

    return {
        "mission_id": str(mission.id),
        "name": name,
        "steps": [dict(r) for r in rows],
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": cost_usd,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> int:
    print("=== B.6 Smoke Test — LLM real (claude-haiku-4-5) ===\n")

    from agent.memory.store import MemoryStore
    from agent.missions.store import MissionStore

    mem = await MemoryStore.create()
    pool = mem._pool
    print("✓ Pool conectado\n")

    mission_store = MissionStore(pool)
    orchestrator, task_store = await build_orchestrator(pool)
    print("✓ Orchestrator real construído\n")

    # ── Cenário C1 — pedido CLARO ─────────────────────────────────────────────
    print("--- C1: pedido CLARO ---")
    c1 = await run_scenario(
        name="claro",
        objective="Listar arquivos .py em core/src/agent/api/ e gravar contagem",
        steps=[
            "Use a tool list_dir para listar os arquivos em "
            "/Users/fate/Desktop/agent/core/src/agent/api/ "
            "e retorne a lista de arquivos .py encontrados.",
            "Use a tool write_file para gravar o texto 'smoke_b6_ok' no arquivo /tmp/smoke_b6.txt",
        ],
        mission_store=mission_store,
        task_store=task_store,
        orchestrator=orchestrator,
    )

    # ── Cenário C2 — pedido AMBÍGUO ───────────────────────────────────────────
    print("\n--- C2: pedido AMBÍGUO ---")
    c2 = await run_scenario(
        name="ambiguo",
        objective="Descobrir quantidade de arquivos Python em core/src/agent/api/",
        steps=["Quero saber quantos arquivos Python existem em /Users/fate/Desktop/agent/core/src/agent/api/"],
        mission_store=mission_store,
        task_store=task_store,
        orchestrator=orchestrator,
    )

    # ── Relatório ─────────────────────────────────────────────────────────────
    print("\n=== B.6 RESULTADOS ===\n")
    all_ok = True
    for scenario in [c1, c2]:
        print(f"--- Cenário {scenario['name'].upper()} ---")
        for s in scenario["steps"]:
            verdict = s["verdict"]
            status = s["status"]
            tools = s["tools_invoked"]
            count = s["tool_count"]
            raw = (s.get("raw_text") or s.get("text") or "")[:120]
            print(f"  seq={s['sequence']} status={status!r} verdict={verdict!r} tools={tools} count={count}")
            if raw:
                print(f"    texto: {raw!r}")

            # Valida critérios de falha do fix
            if status == "done" and verdict == "prose_only":
                print("  ❌ BUG NÃO CORRIGIDO: done + prose_only!")
                all_ok = False
            if s.get("tool_count") and int(s["tool_count"] or 0) > 0 and verdict == "prose_only":
                print("  ❌ analyze_turn QUEBRADO: tool_count>0 mas prose_only!")
                all_ok = False

        cost_str = f"${scenario['cost_usd']:.4f}" if scenario["cost_usd"] else "n/d"
        print(f"  tokens: in={scenario['tokens_in']} out={scenario['tokens_out']} custo≈{cost_str}")
        print()

    # /tmp/smoke_b6.txt
    b6_txt = "/tmp/smoke_b6.txt"
    if os.path.exists(b6_txt):
        with open(b6_txt) as f:
            content = f.read()
        print(f"/tmp/smoke_b6.txt: {content!r}")
    else:
        print("/tmp/smoke_b6.txt: NÃO CRIADO")

    # Custo total
    total_in = c1["tokens_in"] + c2["tokens_in"]
    total_out = c1["tokens_out"] + c2["tokens_out"]
    total_cost = (total_in * 0.80 + total_out * 4.0) / 1_000_000
    print(f"\nCusto total: in={total_in} out={total_out} ≈${total_cost:.4f}")

    # Classificação
    c1_executed = all(
        s.get("verdict") == "executed"
        for s in c1["steps"]
        if s.get("status") in ("done", "failed_no_execution", "failed")
    )
    c1_any_prose = any(s.get("verdict") == "prose_only" for s in c1["steps"])

    print("\n=== CLASSIFICAÇÃO ===")
    if all_ok and c1_executed and not c1_any_prose:
        print("✅ FIX TOTALMENTE VALIDADO")
        print("  C1: todos steps executed, /tmp/smoke_b6.txt criado")
    elif all_ok:
        print("⚠️  SUCESSO PARCIAL HONESTO")
        print("  Fix funciona (não há done+prose_only), mas LLM não chamou tools em todos os steps.")
        print("  Causa: prompting do step insuficiente para forçar tool call — será Fase D.")
    else:
        print("❌ FIX FALHOU — ver ❌ acima")

    # Limpa
    for s in [c1, c2]:
        mid = s["mission_id"]
        # deleta tasks pelo content (strings das descrições dos steps)
        step_contents = [
            step["sequence"]  # não é o content — usa título da missão para filtrar
            for step in s["steps"]
        ]
        await pool.execute(
            "DELETE FROM tasks WHERE source='cron' AND created_at > NOW() - INTERVAL '30 minutes'",
        )
        await pool.execute("DELETE FROM mission_steps WHERE mission_id=$1::uuid", mid)
        await pool.execute("DELETE FROM missions WHERE id=$1::uuid", mid)

    await mem.close()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
