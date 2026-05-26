"""
Subcomando `agent mission` — gerencia missões persistentes.
"""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Gerencia missões persistentes do agente.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http():
    import httpx

    return httpx.AsyncClient(base_url=_CORE_URL, timeout=60)


@app.command("create")
def mission_create(
    objective: str = typer.Option(..., "--objective", "-o", help="Objetivo em linguagem natural"),
    deadline: str | None = typer.Option(None, "--deadline", "-d", help="Prazo (YYYY-MM-DD)"),
    source: str = typer.Option("cli", "--source", "-s"),
) -> None:
    """Cria missão: roda MissionPlanner, exibe plano, pede confirmação."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(
                "/v1/missions/plan",
                json={
                    "objective": objective,
                    "deadline": deadline,
                    "source": source,
                },
            )
            resp.raise_for_status()
            plan = resp.json()

        if "error" in plan:
            console.print(f"[red]Objetivo subjetivo:[/red] {plan.get('reason', 'sem detalhes')}")
            console.print("Refine o objetivo para incluir critérios verificáveis.")
            raise typer.Exit(1)

        console.print(f"\n[bold cyan]Plano proposto:[/bold cyan] {plan['title']}")
        console.print("\n[bold]Critérios de sucesso:[/bold]")
        for c in plan["success_criteria"]:
            console.print(f"  • {c['criterion']} [dim]({c.get('verifiable_via', '?')})[/dim]")

        console.print("\n[bold]Steps:[/bold]")
        for i, step in enumerate(plan["steps"], 1):
            parallel = (
                " [dim][PARALELO][/dim]" if plan.get("is_parallel", [])[i - 1 : i] == [True] else ""
            )
            console.print(f"  {i}. {step}{parallel}")

        confirmed = typer.confirm("\nConfirmar criação da missão?", default=True)
        if not confirmed:
            console.print("[yellow]Cancelado.[/yellow]")
            raise typer.Exit(0)

        async with _http() as client:
            resp = await client.post(
                "/v1/missions",
                json={
                    "objective": objective,
                    "deadline": deadline,
                    "source": source,
                    "plan": plan,
                },
            )
            resp.raise_for_status()
            mission = resp.json()

        console.print(f"\n[green]✓[/green] Missão criada: [bold]{mission['id']}[/bold]")
        console.print(f"  Status: [cyan]{mission['status']}[/cyan]")

    asyncio.run(_run())


@app.command("list")
def mission_list(
    status: str | None = typer.Option(
        None, "--status", "-s", help="active, done, abandoned, failed, all"
    ),
) -> None:
    """Lista missões."""

    async def _run() -> None:
        async with _http() as client:
            params = {} if not status or status == "all" else {"status": status}
            resp = await client.get("/v1/missions", params=params)
            resp.raise_for_status()
            missions = resp.json()

        if not missions:
            console.print("[dim]Nenhuma missão encontrada.[/dim]")
            return

        table = Table(title="Missões")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Título", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Prazo")
        table.add_column("Criada")

        status_colors = {
            "active": "green",
            "done": "blue",
            "paused": "yellow",
            "failed": "red",
            "abandoned": "dim",
        }
        for m in missions:
            color = status_colors.get(m["status"], "white")
            table.add_row(
                m["id"][:8],
                m["title"][:50],
                f"[{color}]{m['status']}[/{color}]",
                m.get("deadline", "—") or "—",
                m["created_at"][:10],
            )
        console.print(table)

    asyncio.run(_run())


@app.command("show")
def mission_show(mission_id: str = typer.Argument(...)) -> None:
    """Exibe detalhes de uma missão: objetivo, critérios, steps, status."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/missions/{mission_id}")
            resp.raise_for_status()
            m = resp.json()

        console.print(f"\n[bold]{m['title']}[/bold]  [{m['status']}]")
        console.print(f"Objetivo: {m['objective']}")
        if m.get("deadline"):
            console.print(f"Prazo: {m['deadline']}")
        console.print("\n[bold]Critérios:[/bold]")
        for c in m["success_criteria"]:
            console.print(f"  • {c['criterion']}")

    asyncio.run(_run())


@app.command("steps")
def mission_steps(mission_id: str = typer.Argument(...)) -> None:
    """Lista os steps de uma missão com status colorido."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/missions/{mission_id}/steps")
            resp.raise_for_status()
            steps = resp.json()

        status_colors = {
            "pending": "dim",
            "running": "yellow",
            "done": "green",
            "failed": "red",
            "skipped": "blue",
        }
        for s in steps:
            color = status_colors.get(s["status"], "white")
            retries = f" [dim](retry={s['retry_count']})[/dim]" if s["retry_count"] else ""
            console.print(
                f"  [{s['sequence']}] [{color}]{s['status']}[/{color}] {s['description']}{retries}"
            )

    asyncio.run(_run())


@app.command("pause")
def mission_pause(mission_id: str = typer.Argument(...)) -> None:
    """Pausa uma missão ativa."""
    asyncio.run(_update_status(mission_id, "paused"))


@app.command("resume")
def mission_resume(mission_id: str = typer.Argument(...)) -> None:
    """Retoma uma missão pausada."""
    asyncio.run(_update_status(mission_id, "active"))


@app.command("abandon")
def mission_abandon(
    mission_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r"),
) -> None:
    """Abandona uma missão (irreversível)."""
    asyncio.run(_update_status(mission_id, "abandoned", reason=reason))


@app.command("replan")
def mission_replan(
    mission_id: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r"),
) -> None:
    """Força MissionPlanner.replan() para a missão."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/v1/missions/{mission_id}/replan", json={"reason": reason})
            resp.raise_for_status()
            console.print("[green]✓[/green] Replan concluído.")

    asyncio.run(_run())


@app.command("reflect")
def mission_reflect(mission_id: str = typer.Argument(...)) -> None:
    """Força MissionReflector para a missão (mesmo que não esteja terminada)."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/v1/missions/{mission_id}/reflect")
            resp.raise_for_status()
            r = resp.json()

        console.print(f"\n[bold]ENTREGUE:[/bold]\n{r['delivered']}")
        console.print(f"\n[bold]QUALIDADE:[/bold]\n{r['quality_assessment']}")
        console.print(f"\n[bold]PRÓXIMO:[/bold]\n{r.get('next_action') or '—'}")
        console.print(f"\n[bold]APRENDIDO:[/bold]\n{r['learned']}")

    asyncio.run(_run())


async def _update_status(mission_id: str, status: str, reason: str | None = None) -> None:
    async with _http() as client:
        resp = await client.patch(
            f"/v1/missions/{mission_id}/status", json={"status": status, "reason": reason}
        )
        resp.raise_for_status()
    console.print(f"[green]✓[/green] Missão → {status}")
