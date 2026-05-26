"""
Subcomando `agent cron` — gerencia cron jobs.
"""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Gerencia cron jobs do agente.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http() -> Any:
    import httpx

    return httpx.AsyncClient(base_url=_CORE_URL, timeout=30)


@app.command("add")
def cron_add(
    schedule: str = typer.Argument(
        ..., help="Cron expression ou linguagem natural (ex: 'toda segunda às 9h')"
    ),
    task: str = typer.Option(..., "--task", "-t", help="Prompt da tarefa a executar"),
    name: str = typer.Option(
        "", "--name", "-n", help="Nome do job (default: primeiras palavras do schedule)"
    ),
    source: str = typer.Option("telegram", "--source", "-s", help="Canal de saída"),
    target: str | None = typer.Option(None, "--target", help="chat_id ou user_id do destino"),
) -> None:
    """Adiciona um novo cron job."""
    job_name = name or schedule[:40]

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(
                "/v1/cron/jobs",
                json={
                    "name": job_name,
                    "schedule": schedule,
                    "task": task,
                    "source": source,
                    "target": target,
                },
            )
            if resp.status_code == 201:
                data = resp.json()
                console.print(f"[green]✓[/green] Job criado: [bold]{data['id']}[/bold]")
                console.print(f"  Cron: [cyan]{data['cron_expr']}[/cyan]")
                if data.get("next_run"):
                    console.print(f"  Próxima execução: {data['next_run']}")
            else:
                console.print(f"[red]Erro {resp.status_code}:[/red] {resp.text}")
                raise typer.Exit(1)

    asyncio.run(_run())


@app.command("list")
def cron_list(
    all_jobs: bool = typer.Option(False, "--all", "-a", help="Incluir jobs desabilitados"),
) -> None:
    """Lista todos os cron jobs."""

    async def _run() -> None:
        async with _http() as client:
            params = {} if all_jobs else {"enabled_only": "true"}
            resp = await client.get("/v1/cron/jobs", params=params)
            resp.raise_for_status()
            jobs = resp.json()

        if not jobs:
            console.print("[dim]Nenhum cron job cadastrado.[/dim]")
            return

        table = Table(title="Cron Jobs")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Nome")
        table.add_column("Cron", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Último", style="dim")
        table.add_column("Próximo", style="green")

        for j in jobs:
            short_id = j["id"][:8]
            status = "[green]ON[/green]" if j["enabled"] else "[red]OFF[/red]"
            last = j.get("last_run", "")[:16] if j.get("last_run") else "—"
            nxt = j.get("next_run", "")[:16] if j.get("next_run") else "—"
            table.add_row(short_id, j["name"], j["cron_expr"], status, last, nxt)

        console.print(table)

    asyncio.run(_run())


@app.command("show")
def cron_show(job_id: str = typer.Argument(..., help="ID do cron job")) -> None:
    """Mostra detalhes de um cron job."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/cron/jobs/{job_id}")
            if resp.status_code == 404:
                console.print("[red]Job não encontrado.[/red]")
                raise typer.Exit(1)
            resp.raise_for_status()
            data = resp.json()

        console.print(f"[bold]ID:[/bold] {data['id']}")
        console.print(f"[bold]Nome:[/bold] {data['name']}")
        console.print(f"[bold]Cron:[/bold] {data['cron_expr']}")
        if data.get("nl_original"):
            console.print(f"[bold]Original:[/bold] {data['nl_original']}")
        console.print(f"[bold]Task:[/bold] {data['task_tpl']}")
        console.print(f"[bold]Source:[/bold] {data['source']}")
        console.print(f"[bold]Habilitado:[/bold] {data['enabled']}")
        console.print(f"[bold]Último status:[/bold] {data.get('last_status', '—')}")
        console.print(f"[bold]Próximo disparo:[/bold] {data.get('next_run', '—')}")

    asyncio.run(_run())


@app.command("enable")
def cron_enable(job_id: str = typer.Argument(..., help="ID do cron job")) -> None:
    """Habilita um cron job."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.patch(f"/v1/cron/jobs/{job_id}/enable")
            resp.raise_for_status()
        console.print(f"[green]✓[/green] Job {job_id[:8]} habilitado.")

    asyncio.run(_run())


@app.command("disable")
def cron_disable(job_id: str = typer.Argument(..., help="ID do cron job")) -> None:
    """Desabilita um cron job (mantém no banco, remove do scheduler)."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.patch(f"/v1/cron/jobs/{job_id}/disable")
            resp.raise_for_status()
        console.print(f"[yellow]⏸[/yellow] Job {job_id[:8]} desabilitado.")

    asyncio.run(_run())


@app.command("remove")
def cron_remove(
    job_id: str = typer.Argument(..., help="ID do cron job"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirmar sem prompt"),
) -> None:
    """Remove um cron job permanentemente."""
    if not yes:
        typer.confirm(f"Remover job {job_id[:8]}?", abort=True)

    async def _run() -> None:
        async with _http() as client:
            resp = await client.delete(f"/v1/cron/jobs/{job_id}")
            if resp.status_code == 404:
                console.print("[red]Job não encontrado.[/red]")
                raise typer.Exit(1)
            if resp.status_code not in (200, 204):
                resp.raise_for_status()
        console.print(f"[red]✗[/red] Job {job_id[:8]} removido.")

    asyncio.run(_run())


@app.command("run-now")
def cron_run_now(job_id: str = typer.Argument(..., help="ID do cron job")) -> None:
    """Dispara o job imediatamente fora do horário (debug)."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/v1/cron/jobs/{job_id}/run-now")
            resp.raise_for_status()
            data = resp.json()
        console.print(f"[green]✓[/green] {data.get('message', 'Job disparado.')}")

    asyncio.run(_run())
