"""
Subcomando `agent critic` — inspeciona avaliações do Crítico Autônomo.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Inspeciona o Crítico Autônomo.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http():
    import httpx
    return httpx.AsyncClient(base_url=_CORE_URL, timeout=30)


@app.command("show")
def critic_show(task_id: str = typer.Argument(..., help="ID da task")) -> None:
    """Exibe os 3 vereditos da última avaliação do Critic para uma task."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/v1/critic/evaluations", params={"task_id": task_id})
            resp.raise_for_status()
            evals = resp.json()

        if not evals:
            console.print("[dim]Nenhuma avaliação encontrada para essa task.[/dim]")
            return

        ev = evals[0]
        console.print(f"\n[bold]Avaliação do Critic[/bold]  [dim]{ev['id'][:8]}[/dim]")
        console.print(f"Veredito final: [bold {'green' if ev['final_verdict'] == 'approve' else 'red'}]{ev['final_verdict']}[/]")

        tech = ev.get("technical_verdict", {})
        devil = ev.get("devils_advocate_verdict", {})
        synth = ev.get("synthesizer_verdict", {})

        console.print("\n[cyan]Técnico:[/cyan]")
        console.print(f"  approve={tech.get('approve')}  confidence={tech.get('confidence')}")
        console.print(f"  {tech.get('reasoning','')[:200]}")

        console.print("\n[yellow]Advogado do Diabo:[/yellow]")
        console.print(f"  approve={devil.get('approve')}  confidence={devil.get('confidence')}")
        for c in devil.get("concerns", [])[:3]:
            console.print(f"  • {c}")

        console.print("\n[magenta]Sintetizador:[/magenta]")
        console.print(f"  {synth.get('reasoning','')[:300]}")
        if ev.get("mitigations"):
            for m in ev["mitigations"]:
                console.print(f"  [dim]mitigação:[/dim] {m}")

        console.print(f"\n[dim]latência: {ev.get('latency_ms','?')}ms[/dim]")

    asyncio.run(_run())


@app.command("stats")
def critic_stats() -> None:
    """Exibe taxa de approve/reject/escalate e latência do Critic."""
    async def _run() -> None:
        async with _http() as client:
            resp = await client.get("/v1/critic/stats")
            resp.raise_for_status()
            stats = resp.json()

        table = Table(title="Critic Stats (24h)")
        table.add_column("Métrica")
        table.add_column("Valor", justify="right")

        for k, v in stats.items():
            if isinstance(v, float):
                table.add_row(k, f"{v:.3f}")
            else:
                table.add_row(k, str(v))
        console.print(table)

    asyncio.run(_run())


@app.command("test")
def critic_test(
    tool: str = typer.Option(..., "--tool", "-t", help="Nome da tool"),
    args: str = typer.Option("{}", "--args", "-a", help="JSON dos args"),
    context: str = typer.Option("Teste manual via CLI", "--context", "-c"),
) -> None:
    """Dry-run do Critic: avalia sem executar a tool."""
    async def _run() -> None:
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            console.print("[red]--args deve ser JSON válido[/red]")
            raise typer.Exit(1)

        async with _http() as client:
            resp = await client.post("/v1/critic/test", json={
                "tool_name": tool,
                "tool_args": parsed_args,
                "context_summary": context,
            })
            resp.raise_for_status()
            result = resp.json()

        verdict = result.get("verdict", "?")
        color = {"approve": "green", "reject": "red",
                 "approve_with_mitigation": "yellow", "escalate": "magenta"}.get(verdict, "white")
        console.print(f"\nVeredito: [{color}]{verdict}[/{color}]")
        console.print(f"Raciocínio: {result.get('reasoning','')[:300]}")
        if result.get("mitigations"):
            for m in result["mitigations"]:
                console.print(f"  [dim]mitigação:[/dim] {m}")

    asyncio.run(_run())
