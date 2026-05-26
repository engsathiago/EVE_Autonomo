"""
Subcomando `agent finetune` — run, list, activate, rollback, report, bench.

Todos os subcomandos requerem dependências do grupo [finetune] instaladas.
Se não instaladas, exibe mensagem clara com instrução de instalação.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Fine-tuning local com LoRA e benchmark gates.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")
_PROJECT_ROOT = Path(__file__).parents[5]  # agent/


def _check_finetune_deps() -> None:
    """Validates that the [finetune] extras are installed. Fails fast with a clear message."""
    missing = []
    for pkg in ["peft", "transformers", "bitsandbytes", "datasets"]:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)
    if missing:
        console.print("[red]Dependências do grupo [finetune] não instaladas:[/red]")
        console.print(f"  Faltando: {', '.join(missing)}")
        console.print("\nInstale com:")
        console.print("  [cyan]pip install 'agent-core[finetune]'[/cyan]")
        raise typer.Exit(1)


def _get_pool():
    """Creates a synchronous asyncpg pool wrapper for CLI use."""
    import asyncpg

    db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
    return asyncpg.connect(db_url)


def _load_finetune_config() -> dict:
    config_path = _PROJECT_ROOT / "config" / "finetune.yaml"
    if not config_path.exists():
        console.print(f"[yellow]Config não encontrado:[/yellow] {config_path}")
        console.print("Crie config/finetune.yaml — veja docs/finetune.md para o formato.")
        raise typer.Exit(1)
    import yaml

    return yaml.safe_load(config_path.read_text()) or {}


@app.command("run")
def finetune_run(
    auto_activate: bool = typer.Option(
        False, "--auto-activate", help="Ativa automaticamente se aprovado (só após N runs manuais)"
    ),
    triggered_by: str = typer.Option(
        "cli", "--triggered-by", help="Quem disparou: 'cli', 'cron:weekly', etc."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Só coleta e exibe estatísticas do dataset, sem treinar"
    ),
) -> None:
    """Executa um ciclo completo: coleta → dataset → benchmark → treino → gate → relatório."""
    _check_finetune_deps()

    async def _run() -> None:
        import uuid

        import asyncpg
        from agent.finetune.benchmark_runner import BenchmarkRunner
        from agent.finetune.checkpoint_gate import CheckpointGate
        from agent.finetune.checkpoint_registry import CheckpointRegistry
        from agent.finetune.dataset_builder import DatasetBuilder
        from agent.finetune.exceptions import BenchmarkError, DatasetTooSmall
        from agent.finetune.lora_trainer import LoraTrainer, TrainConfig
        from agent.finetune.reports import generate_report, notify_telegram
        from agent.finetune.rubric import Rubric
        from agent.finetune.safety_check import SafetyCheck
        from agent.finetune.trace_collector import TraceCollector

        cfg_raw = _load_finetune_config()
        ft_cfg = cfg_raw.get("finetune", {})
        training_cfg = ft_cfg.get("training", {})
        bench_cfg = ft_cfg.get("benchmark", {})
        notif_cfg = ft_cfg.get("notification", {})

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

        benchmarks_dir = _PROJECT_ROOT / "benchmarks"
        rubric_path = benchmarks_dir / bench_cfg.get("rubric_path", "rubric.yaml").replace(
            "benchmarks/", ""
        )

        # C1: Benchmark é pré-requisito — falha explícita se rubric.yaml não existe
        try:
            rubric = Rubric.load(rubric_path)
        except BenchmarkError as exc:
            console.print(f"[red]BenchmarkError:[/red] {exc}")
            raise typer.Exit(1)

        run_id = str(uuid.uuid4())
        base_model = ft_cfg.get("base_model", "qwen2.5-7b-instruct")
        models_dir = _PROJECT_ROOT / "models"
        datasets_dir = _PROJECT_ROOT / "datasets"

        registry = CheckpointRegistry(
            pool=pool,
            models_dir=models_dir,
            auto_activate=ft_cfg.get("activation", {}).get("auto_activate", False),
            auto_activate_after_n_accepted=ft_cfg.get("activation", {}).get(
                "auto_activate_after_n_accepted", 5
            ),
        )

        console.print(f"\n[bold cyan]F13 Fine-tuning — Run {run_id[:8]}[/bold cyan]")
        console.print(f"  Base model: [dim]{base_model}[/dim]")
        console.print(f"  Triggered by: [dim]{triggered_by}[/dim]\n")

        # Step 1: Collect traces
        console.print("[bold]1.[/bold] Coletando traces...")
        collector = TraceCollector(
            pool=pool,
            min_quality_score=ft_cfg.get("trace_collection", {}).get("min_quality_score", 0.7),
            lookback_days=ft_cfg.get("trace_collection", {}).get("lookback_days", 30),
            exclude_skills=ft_cfg.get("trace_collection", {}).get("exclude_skills", []),
            max_dataset_size=ft_cfg.get("trace_collection", {}).get("max_dataset_size", 5000),
        )
        raw_records = await collector.collect()
        console.print(f"   {len(raw_records)} traces coletados")

        # Step 2: Build dataset
        console.print("[bold]2.[/bold] Construindo dataset...")
        builder = DatasetBuilder(
            output_dir=datasets_dir,
            min_dataset_size=ft_cfg.get("trace_collection", {}).get("min_dataset_size", 100),
            max_dataset_size=ft_cfg.get("trace_collection", {}).get("max_dataset_size", 5000),
        )
        try:
            dataset_path, stats = builder.build(raw_records)
        except DatasetTooSmall as exc:
            console.print(f"[red]DatasetTooSmall:[/red] {exc}")
            raise typer.Exit(1)

        console.print(
            f"   {stats.train_size} treino + {stats.eval_size} eval | ID: {stats.dataset_id}"
        )

        if dry_run:
            console.print("\n[yellow]--dry-run: parando aqui (sem treino).[/yellow]")
            await pool.close()
            return

        # Register run in DB
        train_config = TrainConfig(
            base_model=base_model,
            lora_r=training_cfg.get("lora_r", 16),
            lora_alpha=training_cfg.get("lora_alpha", 32),
            lora_dropout=training_cfg.get("lora_dropout", 0.05),
            learning_rate=training_cfg.get("learning_rate", 2e-4),
            epochs=training_cfg.get("epochs", 2),
            batch_size=training_cfg.get("batch_size", 4),
            gradient_accumulation=training_cfg.get("gradient_accumulation", 4),
            max_seq_length=training_cfg.get("max_seq_length", 2048),
            use_unsloth=training_cfg.get("use_unsloth", True),
        )
        await registry.create_run(
            run_id=run_id,
            base_model=base_model,
            dataset_path=dataset_path,
            dataset_size=stats.train_size + stats.eval_size,
            config=train_config.to_dict(),
            triggered_by=triggered_by,
        )

        # Step 3: Benchmark base (with cache)
        console.print("[bold]3.[/bold] Benchmark do modelo base...")
        base_model_ref = f"base:{base_model}"
        bench_runner = BenchmarkRunner(
            rubric=rubric,
            benchmarks_dir=benchmarks_dir,
            pool=pool,
            ollama_base_url=ollama_url,
            anthropic_api_key=anthropic_key,
            base_score_cache_days=bench_cfg.get("base_score_cache_days", 7),
        )
        base_scores = await bench_runner.run(model_ref=base_model_ref, run_id=None)
        console.print(f"   Base score ponderado: {rubric.weighted_score(base_scores):.4f}")

        # Step 4: Train
        console.print("[bold]4.[/bold] Treinando LoRA...")
        trainer = LoraTrainer(
            checkpoints_dir=models_dir / "checkpoints", ollama_base_url=ollama_url
        )
        from agent.finetune.exceptions import FinetuneError

        try:
            train_result = await trainer.train(
                dataset_path=dataset_path, run_id=run_id, config=train_config
            )
        except FinetuneError as exc:
            await registry.finish_run(run_id=run_id, status="failed", rejection_reason=str(exc))
            console.print(f"[red]Treino falhou:[/red] {exc}")
            raise typer.Exit(1)

        checkpoint_id = train_result.checkpoint_dir.name
        console.print(f"   Checkpoint: {checkpoint_id} | Loss: {train_result.final_loss}")

        # Step 5: Benchmark candidate
        console.print("[bold]5.[/bold] Benchmark do candidato...")
        cand_model_ref = f"checkpoint:{train_result.ollama_model_name}"
        cand_scores = await bench_runner.run(model_ref=cand_model_ref, run_id=run_id)
        console.print(f"   Candidato score ponderado: {rubric.weighted_score(cand_scores):.4f}")

        # Step 6: Safety check
        console.print("[bold]6.[/bold] Safety check...")
        safety = SafetyCheck(
            safety_tasks_dir=benchmarks_dir / "tasks" / "safety",
            ollama_base_url=ollama_url,
        )
        safety_result = await safety.run(
            base_model_ref=base_model_ref,
            candidate_model_ref=cand_model_ref,
        )
        console.print(f"   Safety: {'✅ passou' if safety_result.passed else '❌ falhou'}")

        # Step 7: Gate decision
        gate = CheckpointGate(rubric=rubric, safety_strict=bench_cfg.get("safety_strict", True))
        decision = gate.decide(base_scores, cand_scores, safety_result)

        # Step 8: Persist checkpoint
        await registry.create_checkpoint(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            base_model=base_model,
            path=train_result.checkpoint_dir,
            benchmark_score={"base": base_scores, "candidate": cand_scores},
        )

        final_status = "accepted" if decision.accepted else "rejected"
        if not decision.accepted:
            await registry.reject_checkpoint(checkpoint_id)

        await registry.finish_run(
            run_id=run_id,
            status=final_status,
            checkpoint_id=checkpoint_id if decision.accepted else None,
            benchmark_score={"base": base_scores, "candidate": cand_scores},
            rejection_reason=None if decision.accepted else decision.reason,
        )

        # Step 9: Auto-activate if configured and allowed
        if auto_activate and decision.accepted:
            try:
                can = await registry.can_auto_activate()
                if can:
                    await registry.activate(checkpoint_id, auto=True)
                    console.print(f"   [green]Auto-ativado:[/green] {checkpoint_id}")
                else:
                    console.print(
                        "   [yellow]auto_activate=true mas histórico insuficiente. Ative manualmente.[/yellow]"
                    )
            except Exception as exc:
                console.print(f"   [yellow]Auto-ativação falhou:[/yellow] {exc}")

        # Step 10: Generate report
        report_path = train_result.checkpoint_dir / "benchmark_report.md"
        report_text = generate_report(
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            base_model=base_model,
            base_scores=base_scores,
            candidate_scores=cand_scores,
            gate_decision=decision,
            safety_result=safety_result,
            dataset_size=stats.train_size + stats.eval_size,
            config=train_config.to_dict(),
            output_path=report_path,
            triggered_by=triggered_by,
        )

        # Telegram notification (optional)
        tg_chat = notif_cfg.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID")
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        await notify_telegram(
            report_summary=report_text[:500],
            run_id=run_id,
            decision=final_status.upper(),
            telegram_chat_id=tg_chat,
            telegram_token=tg_token,
        )

        console.print(
            f"\n[bold]Resultado:[/bold] {'[green]APROVADO[/green]' if decision.accepted else '[red]REJEITADO[/red]'}"
        )
        if not decision.accepted:
            console.print(f"  Razão: {decision.reason}")
        console.print(f"  Relatório: {report_path}")
        await pool.close()

    asyncio.run(_run())


@app.command("list")
def finetune_list(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Lista runs e checkpoints recentes com status e scores."""

    async def _run() -> None:
        import asyncpg

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        conn = await asyncpg.connect(db_url)

        runs = await conn.fetch(
            """
            SELECT id, started_at, status, base_model, dataset_size,
                   benchmark_score, rejection_reason, triggered_by
            FROM finetune_runs ORDER BY started_at DESC LIMIT $1
            """,
            limit,
        )
        await conn.close()

        table = Table(title="Fine-tuning Runs", show_lines=True)
        table.add_column("ID", width=10)
        table.add_column("Status", width=10)
        table.add_column("Base model", width=22)
        table.add_column("Dataset", width=8)
        table.add_column("Score Δ%", width=9)
        table.add_column("Disparado por", width=16)
        table.add_column("Data", width=18)

        for r in runs:
            scores = r["benchmark_score"] or {}
            import json

            if isinstance(scores, str):
                scores = json.loads(scores)
            base_w = scores.get("base_weighted", 0)
            cand_w = scores.get("candidate_weighted", 0)
            delta_str = f"{(cand_w - base_w) * 100:+.2f}%" if base_w and cand_w else "—"
            status_color = {
                "accepted": "green",
                "rejected": "red",
                "running": "yellow",
                "failed": "red",
            }.get(r["status"], "white")

            table.add_row(
                r["id"][:8],
                f"[{status_color}]{r['status']}[/{status_color}]",
                r["base_model"],
                str(r["dataset_size"]),
                delta_str,
                r["triggered_by"],
                str(r["started_at"])[:16] if r["started_at"] else "?",
            )
        console.print(table)

    asyncio.run(_run())


@app.command("activate")
def finetune_activate(
    checkpoint_id: str = typer.Argument(..., help="ID do checkpoint a ativar"),
) -> None:
    """Ativa um checkpoint candidato atomicamente."""

    async def _run() -> None:
        import asyncpg
        from agent.finetune.checkpoint_registry import CheckpointRegistry

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        models_dir = _PROJECT_ROOT / "models"
        registry = CheckpointRegistry(pool=pool, models_dir=models_dir)
        try:
            await registry.activate(checkpoint_id)
            console.print(f"[green]✓[/green] Checkpoint [bold]{checkpoint_id}[/bold] ativado.")
            console.print(f"  active_checkpoint.txt: {models_dir / 'active_checkpoint.txt'}")
        except Exception as exc:
            console.print(f"[red]Erro ao ativar:[/red] {exc}")
            raise typer.Exit(1)
        finally:
            await pool.close()

    asyncio.run(_run())


@app.command("rollback")
def finetune_rollback() -> None:
    """Volta para o checkpoint anterior (ou base se nenhum anterior)."""

    async def _run() -> None:
        import asyncpg
        from agent.finetune.checkpoint_registry import CheckpointRegistry

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        models_dir = _PROJECT_ROOT / "models"
        registry = CheckpointRegistry(pool=pool, models_dir=models_dir)
        try:
            rolled_to = await registry.rollback()
            console.print(f"[green]✓[/green] Rollback para: [bold]{rolled_to}[/bold]")
        except Exception as exc:
            console.print(f"[red]Erro no rollback:[/red] {exc}")
            raise typer.Exit(1)
        finally:
            await pool.close()

    asyncio.run(_run())


@app.command("report")
def finetune_report(
    run_id: str = typer.Argument(..., help="Run ID (prefix de 8 chars também aceito)"),
) -> None:
    """Exibe o benchmark_report.md de um run."""

    async def _run() -> None:
        import asyncpg

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        conn = await asyncpg.connect(db_url)
        row = await conn.fetchrow(
            "SELECT id, checkpoint_id FROM finetune_runs WHERE id LIKE $1 LIMIT 1",
            f"{run_id}%",
        )
        await conn.close()
        if not row:
            console.print(f"[red]Run não encontrado:[/red] {run_id}")
            raise typer.Exit(1)

        if not row["checkpoint_id"]:
            console.print("[yellow]Run sem checkpoint (rejeitado ou falhou).[/yellow]")
            raise typer.Exit(1)

        ckpt_id = row["checkpoint_id"]
        report_path = _PROJECT_ROOT / "models" / "checkpoints" / ckpt_id / "benchmark_report.md"
        if not report_path.exists():
            console.print(f"[red]Relatório não encontrado:[/red] {report_path}")
            raise typer.Exit(1)

        from rich.markdown import Markdown

        console.print(Markdown(report_path.read_text()))

    asyncio.run(_run())


@app.command("bench")
def finetune_bench(
    model: str = typer.Option(..., "--model", "-m", help="'base' ou 'checkpoint:<id>'"),
    run_id: str | None = typer.Option(None, "--run-id", help="Run ID para associar resultados"),
) -> None:
    """Roda apenas o benchmark (sem treinar). Útil para estabelecer baseline."""
    _check_finetune_deps()

    async def _run() -> None:
        import asyncpg
        from agent.finetune.benchmark_runner import BenchmarkRunner
        from agent.finetune.exceptions import BenchmarkError
        from agent.finetune.rubric import Rubric

        cfg_raw = _load_finetune_config()
        ft_cfg = cfg_raw.get("finetune", {})
        bench_cfg = ft_cfg.get("benchmark", {})
        base_model = ft_cfg.get("base_model", "qwen2.5-7b-instruct")

        benchmarks_dir = _PROJECT_ROOT / "benchmarks"
        rubric_path = benchmarks_dir / bench_cfg.get("rubric_path", "rubric.yaml").replace(
            "benchmarks/", ""
        )

        try:
            rubric = Rubric.load(rubric_path)
        except BenchmarkError as exc:
            console.print(f"[red]BenchmarkError:[/red] {exc}")
            raise typer.Exit(1)

        db_url = os.getenv("DATABASE_URL", "postgresql://agent:agent@localhost:5432/agent")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        model_ref = f"base:{base_model}" if model == "base" else model
        console.print(f"[bold]Benchmark:[/bold] {model_ref}\n")

        runner = BenchmarkRunner(
            rubric=rubric,
            benchmarks_dir=benchmarks_dir,
            pool=pool,
            ollama_base_url=ollama_url,
            anthropic_api_key=anthropic_key,
            base_score_cache_days=bench_cfg.get("base_score_cache_days", 7),
        )
        scores = await runner.run(model_ref=model_ref, run_id=run_id)

        table = Table(title=f"Benchmark — {model_ref}")
        table.add_column("Eixo", width=24)
        table.add_column("Score", width=8)
        for axis, score in sorted(scores.items()):
            table.add_row(axis, f"{score:.4f}")

        weighted = rubric.weighted_score(scores)
        console.print(table)
        console.print(f"\n[bold]Score ponderado:[/bold] {weighted:.4f}")
        await pool.close()

    asyncio.run(_run())
