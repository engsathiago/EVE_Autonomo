"""CLI db — aplica migrations do banco de dados."""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console

app = typer.Typer(help="Gerencia o schema do banco de dados.")
console = Console()


def _build_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN")
    if dsn:
        return dsn
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "agent")
    pwd = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DB", "agent")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


@app.command()
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Lista pendentes sem aplicar"),
    stamp: bool = typer.Option(
        False, "--stamp",
        help="Registra todas as migrations como aplicadas SEM executar SQL (bootstrap)",
    ),
) -> None:
    """Aplica migrations SQL pendentes (idempotente)."""
    from agent.db.migrate import apply_migrations, stamp_all

    dsn = _build_dsn()

    async def _run() -> list[str]:
        if stamp:
            return await stamp_all(dsn)
        return await apply_migrations(dsn, dry_run=dry_run)

    try:
        applied = asyncio.run(_run())
    except Exception as exc:
        console.print(f"[red]Erro ao conectar ao banco:[/red] {exc}")
        raise typer.Exit(1) from exc

    if stamp:
        if applied:
            console.print(f"[yellow]Carimbadas {len(applied)} migration(s) (stamp):[/yellow] {applied}")
        else:
            console.print("[green]Todas as migrations já estavam registradas.[/green]")
    elif dry_run:
        if applied:
            console.print(f"[yellow]Migrations pendentes ({len(applied)}):[/yellow]")
            for v in applied:
                console.print(f"  • {v}")
        else:
            console.print("[green]Nenhuma migration pendente.[/green]")
    else:
        if applied:
            console.print(f"[green]Aplicadas {len(applied)} migration(s):[/green] {applied}")
        else:
            console.print("[green]Banco já atualizado — nenhuma migration pendente.[/green]")
