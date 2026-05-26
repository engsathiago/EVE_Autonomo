"""
Subcomando `agent loop` — controla o AutonomousLoop.
"""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console

app = typer.Typer(help="Controla o AutonomousLoop.")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http():
    import httpx

    return httpx.AsyncClient(base_url=_CORE_URL, timeout=60)


@app.command("status")
def loop_status() -> None:
    """Exibe tick atual, missões ativas e próximos steps."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get("/v1/loop/status")
            resp.raise_for_status()
            s = resp.json()

        console.print(f"\n[bold]AutonomousLoop[/bold]  running={s.get('running', False)}")
        console.print(f"Missões ativas: {s.get('missions_active', 0)}")
        console.print(f"Último tick: {s.get('last_tick_at', '—')}")
        console.print(f"Steps disparados (último tick): {s.get('last_steps_dispatched', 0)}")
        console.print(f"Intervalo: {s.get('tick_interval_minutes', 5)} min")

        upcoming = s.get("upcoming_steps", [])
        if upcoming:
            console.print("\n[bold]Próximos steps:[/bold]")
            for step in upcoming[:5]:
                console.print(
                    f"  • [{step['mission_title'][:30]}] seq={step['sequence']} {step['description'][:60]}"
                )

    asyncio.run(_run())


@app.command("tick-now")
def loop_tick_now() -> None:
    """Força um tick imediato (debug)."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post("/v1/loop/tick")
            resp.raise_for_status()
            report = resp.json()

        console.print("[green]✓[/green] Tick executado")
        console.print(f"  Missões verificadas: {report.get('missions_checked', 0)}")
        console.print(f"  Steps disparados: {report.get('steps_dispatched', 0)}")
        console.print(f"  Steps falhos: {report.get('steps_failed', 0)}")
        console.print(f"  Replans: {report.get('replans_triggered', 0)}")
        console.print(f"  Missões concluídas: {report.get('missions_completed', 0)}")

    asyncio.run(_run())


@app.command("pause")
def loop_pause() -> None:
    """Pausa o loop globalmente."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post("/v1/loop/pause")
            resp.raise_for_status()
        console.print("[yellow]Loop pausado.[/yellow]")

    asyncio.run(_run())


@app.command("resume")
def loop_resume() -> None:
    """Retoma o loop pausado."""

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post("/v1/loop/resume")
            resp.raise_for_status()
        console.print("[green]Loop retomado.[/green]")

    asyncio.run(_run())
