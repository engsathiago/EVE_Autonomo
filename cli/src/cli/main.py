import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from cli import __version__

from cli.skills import app as skills_app

app = typer.Typer(name="agent", help="Agente autônomo híbrido — CLI de controle.")
app.add_typer(skills_app, name="skill")
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
def run() -> None:
    """Inicia o REPL interativo da Eve."""
    from agent.observability import configure_logging
    from agent.config import get_settings

    settings = get_settings()
    configure_logging(settings.log_level)

    from cli.repl import run_repl
    asyncio.run(run_repl())
