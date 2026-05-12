import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cli import __version__

from cli.models import app as models_app
from cli.skills import app as skills_app
from cli.cron import app as cron_app
from cli.tasks import app as tasks_app
from cli.missions import app as missions_app
from cli.critic_cli import app as critic_app
from cli.reflexive_memory_cli import app as reflexive_app
from cli.loop_cli import app as loop_app
from cli.deploy_cmd import app as deploy_app

# Subcomando `agent memory` agrupa memória semântica e reflexiva
_memory_app = typer.Typer(help="Gerencia memória do agente (semântica + reflexiva).")
_memory_app.add_typer(reflexive_app, name="reflexive")

app = typer.Typer(name="agent", help="Agente autônomo híbrido — CLI de controle.")
app.add_typer(skills_app, name="skill")
app.add_typer(models_app, name="model")
app.add_typer(cron_app, name="cron")
app.add_typer(tasks_app, name="task")
app.add_typer(missions_app, name="mission")
app.add_typer(critic_app, name="critic")
app.add_typer(_memory_app, name="memory")
app.add_typer(loop_app, name="loop")
app.add_typer(deploy_app, name="deploy")
console = Console()


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agent v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
) -> None:
    pass


@app.command()
def setup() -> None:
    """Valida configuração e variáveis de ambiente necessárias."""
    missing = []
    for var in ["ANTHROPIC_API_KEY"]:
        if not os.environ.get(var):
            missing.append(var)

    if missing:
        console.print(f"[red]Variáveis ausentes: {', '.join(missing)}[/red]")
        console.print("Configure seu .env — veja .env.example")
        raise typer.Exit(1)

    console.print("[green]✓[/green] Configuração OK")
    console.print(f"[dim]Arquivo .env: {Path('.env').resolve()}[/dim]")


@app.command()
def run(
    goal: Optional[str] = typer.Argument(None, help="Objetivo one-shot. Sem argumento, abre o REPL."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="ex: ollama:qwen2.5:7b"),
) -> None:
    """Executa um goal one-shot ou inicia o REPL interativo da Eve."""
    from agent.config import build_model_router, get_settings
    from agent.observability import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)

    if goal is None:
        from cli.repl import run_repl
        asyncio.run(run_repl())
        return

    # One-shot
    async def _run_once() -> None:
        import sys
        from agent.core import AIAgent
        from agent.memory.store import MemoryStore
        from agent.tools.registry import ToolRegistry, register_builtin
        from agent.transports import AnthropicTransport

        store = await MemoryStore.create()
        registry = ToolRegistry()
        register_builtin(registry)

        router = build_model_router(settings, db_pool=store._pool)
        planner = AnthropicTransport(model=settings.anthropic.planner_model)
        reflector = AnthropicTransport(model=settings.anthropic.reflector_model)

        agent = AIAgent(
            transport=planner,
            tool_registry=registry,
            reflector_transport=reflector,
            model_router=router,
        )

        effective_model = model or settings.models.default_model
        console.print(f"[dim]modelo: {effective_model}[/dim]")

        result = await agent.run(goal=goal, model_override=effective_model)
        console.print(result.final_text)
        console.print(
            f"[dim]{result.iterations} iter · "
            f"{result.total_input_tokens}+{result.total_output_tokens} tokens · "
            f"${result.estimated_cost_usd:.6f} · {result.duration_s:.1f}s[/dim]"
        )
        await store.close()

    asyncio.run(_run_once())
