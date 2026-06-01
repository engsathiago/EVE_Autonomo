"""
Subcomando `agent memory reflexive` — gerencia memória reflexiva.
"""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Gerencia a memória reflexiva (lições aprendidas).")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http():
    import httpx

    return httpx.AsyncClient(base_url=_CORE_URL, timeout=30)


@app.command("list")
def reflexive_list(
    limit: int = typer.Option(20, "--limit", "-n"),
    include_forgotten: bool = typer.Option(False, "--all", "-a", help="Incluir esquecidos"),
) -> None:
    """Lista insights da memória reflexiva."""

    async def _run() -> None:
        async with _http() as client:
            params = {"limit": str(limit)}
            if include_forgotten:
                params["include_forgotten"] = "true"
            resp = await client.get("/v1/memory/reflexive", params=params)
            resp.raise_for_status()
            insights = resp.json()

        if not insights:
            console.print("[dim]Nenhum insight na memória reflexiva.[/dim]")
            return

        table = Table(title="Memória Reflexiva")
        table.add_column("ID", style="dim", max_width=8)
        table.add_column("Insight")
        table.add_column("Relevância", justify="right")
        table.add_column("Recalls", justify="right")
        table.add_column("Status", justify="center")

        for i in insights:
            status = "[dim]esquecido[/dim]" if i.get("forgotten") else "[green]ativo[/green]"
            table.add_row(
                i["id"][:8],
                i["insight"][:80],
                f"{i['relevance_score']:.2f}",
                str(i["times_recalled"]),
                status,
            )
        console.print(table)

    asyncio.run(_run())


@app.command("search")
def reflexive_search(
    query: str = typer.Argument(..., help="Query de busca semântica"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
) -> None:
    """Busca insights relevantes por similaridade semântica."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post("/v1/memory/reflexive/search", json={"query": query, "top_k": top_k})
            resp.raise_for_status()
            results = resp.json()

        if not results:
            console.print("[dim]Nenhum resultado encontrado.[/dim]")
            return

        for i, r in enumerate(results, 1):
            console.print(f"\n[bold]{i}.[/bold] {r['insight']}")
            console.print(f"   [dim]relevância={r['relevance_score']:.2f}  recalls={r['times_recalled']}[/dim]")

    asyncio.run(_run())


@app.command("forget")
def reflexive_forget(insight_id: str = typer.Argument(...)) -> None:
    """Marca um insight como esquecido manualmente."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.delete(f"/v1/memory/reflexive/{insight_id}")
            resp.raise_for_status()
        console.print(f"[green]✓[/green] Insight {insight_id[:8]}… marcado como esquecido.")

    asyncio.run(_run())
