"""
Subcomando `agent task` — gerencia tasks e vê árvore de subagentes.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

app = typer.Typer(help="Gerencia tasks e subagentes.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http() -> "Any":
    import httpx
    return httpx.AsyncClient(base_url=_CORE_URL, timeout=30)


@app.command("list")
def task_list(
    status: Optional[str] = typer.Option(None, "--status", "-s",
        help="Filtrar por status: pending, running, done, failed, timeout"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Lista tasks recentes."""
    async def _run() -> None:
        async with _http() as client:
            params: dict = {"limit": str(limit)}
            if status:
                params["status"] = status
            resp = await client.get("/v1/tasks", params=params)
            resp.raise_for_status()
            tasks = resp.json()

        if not tasks:
            console.print("[dim]Nenhuma task encontrada.[/dim]")
            return

        table = Table(title="Tasks")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Source", style="cyan")
        table.add_column("Tier", justify="center")
        table.add_column("Status", justify="center")
        table.add_column("Iter")
        table.add_column("Content", max_width=40)

        STATUS_STYLE = {
            "done": "[green]done[/green]",
            "running": "[yellow]running[/yellow]",
            "failed": "[red]failed[/red]",
            "timeout": "[red]timeout[/red]",
            "pending": "[dim]pending[/dim]",
        }

        for t in tasks:
            short_id = t["id"][:8]
            tier = t.get("tier") or "—"
            status_str = STATUS_STYLE.get(t["status"], t["status"])
            content = t["content"][:40]
            table.add_row(short_id, t["source"], tier, status_str, str(t["iterations"]), content)

        console.print(table)

    asyncio.run(_run())


@app.command("show")
def task_show(task_id: str = typer.Argument(..., help="ID da task")) -> None:
    """Mostra detalhes de uma task."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/tasks/{task_id}")
            if resp.status_code == 404:
                console.print("[red]Task não encontrada.[/red]")
                raise typer.Exit(1)
            resp.raise_for_status()
            t = resp.json()

        console.print(f"[bold]ID:[/bold] {t['id']}")
        console.print(f"[bold]Source:[/bold] {t['source']}")
        console.print(f"[bold]Tier:[/bold] {t.get('tier', '—')}")
        console.print(f"[bold]Status:[/bold] {t['status']}")
        console.print(f"[bold]Iterações:[/bold] {t['iterations']}")
        console.print(f"[bold]Tokens in/out:[/bold] {t['tokens_in']} / {t['tokens_out']}")
        if t.get("error"):
            console.print(f"[bold red]Erro:[/bold red] {t['error']}")
        console.print(f"[bold]Criada:[/bold] {t['created_at']}")
        console.print(f"\n[bold]Conteúdo:[/bold]\n{t['content']}")

    asyncio.run(_run())


@app.command("tree")
def task_tree(task_id: str = typer.Argument(..., help="ID da task raiz")) -> None:
    """Exibe árvore pai → filhos de uma task EPIC."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/tasks/{task_id}/tree")
            if resp.status_code == 404:
                console.print("[red]Task não encontrada.[/red]")
                raise typer.Exit(1)
            resp.raise_for_status()
            tasks = resp.json()

        if not tasks:
            console.print("[dim]Nenhuma task.[/dim]")
            return

        by_id = {t["id"]: t for t in tasks}
        root = next((t for t in tasks if t["parent_id"] is None), tasks[0])

        def _add_children(tree_node: Tree, parent_id: str) -> None:
            for t in tasks:
                if t["parent_id"] == parent_id:
                    label = (
                        f"[dim]{t['id'][:8]}[/dim] "
                        f"[cyan]{t.get('tier', '?')}[/cyan] "
                        f"{t['status']} — {t['content'][:50]}"
                    )
                    child = tree_node.add(label)
                    _add_children(child, t["id"])

        root_label = (
            f"[bold]{root['id'][:8]}[/bold] "
            f"[cyan]{root.get('tier', '?')}[/cyan] "
            f"{root['status']} — {root['content'][:50]}"
        )
        tree = Tree(root_label)
        _add_children(tree, root["id"])
        console.print(tree)

    asyncio.run(_run())


@app.command("cancel")
def task_cancel(task_id: str = typer.Argument(..., help="ID da task")) -> None:
    """Cancela uma task pendente ou em execução."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/v1/tasks/{task_id}/cancel")
            if resp.status_code == 404:
                console.print("[red]Task não encontrada ou já finalizada.[/red]")
                raise typer.Exit(1)
            resp.raise_for_status()
        console.print(f"[yellow]⏹[/yellow] Task {task_id[:8]} cancelada.")

    asyncio.run(_run())


@app.command("stats")
def orchestrator_stats() -> None:
    """Exibe estatísticas do orchestrator por tier nas últimas 24h."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.get("/v1/tasks/orchestrator/stats")
            resp.raise_for_status()
            stats = resp.json()

        if "error" in stats:
            console.print(f"[red]{stats['error']}[/red]")
            return

        table = Table(title="Orchestrator Stats (últimas 24h)")
        table.add_column("Tier", style="cyan")
        table.add_column("Execuções", justify="right")
        table.add_column("p50 (s)", justify="right")
        table.add_column("p95 (s)", justify="right")

        for tier, data in stats.items():
            table.add_row(
                tier,
                str(data["count_24h"]),
                str(data["p50_s"]),
                str(data["p95_s"]),
            )

        console.print(table)

    asyncio.run(_run())
