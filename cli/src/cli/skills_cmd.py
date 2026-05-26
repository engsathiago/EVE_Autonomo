"""
Subcomando `agent skills` — gerencia skills auto-geradas (Fase 9).

Todos os comandos batem na API HTTP /api/v1/skills/*.
Sem SQL direto.
"""

from __future__ import annotations

import json
import os
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Gerencia skills auto-geradas (F9).")
console = Console()

_CORE_URL = os.getenv("AGENT_CORE_URL", "http://localhost:8000")


def _http() -> Any:  # type: ignore[name-defined]
    import httpx

    return httpx.AsyncClient(base_url=_CORE_URL, timeout=60)


@app.command("list")
def skills_list(
    status: Annotated[str | None, typer.Option("--status", "-s")] = None,
) -> None:
    """Lista skills (--status=active|pending|rejected|deprecated|mature)."""
    import asyncio

    async def _run() -> None:
        params = {"status": status} if status else {}
        async with _http() as client:
            resp = await client.get("/api/v1/skills", params=params)
            resp.raise_for_status()
            skills = resp.json()

        if not skills:
            console.print("[yellow]Nenhuma skill encontrada.[/yellow]")
            return

        table = Table(title=f"Skills (status={status or 'all'})")
        table.add_column("Slug", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Version")
        table.add_column("Execuções")
        table.add_column("Último uso")
        for s in skills:
            manifest = json.loads(s.get("manifest_json", "{}"))
            table.add_row(
                s["slug"],
                s.get("status", "?"),
                str(s.get("version", 1)),
                str(s.get("executions_count", 0)),
                str(s.get("last_used_at", "nunca")),
            )
        console.print(table)

    asyncio.run(_run())


@app.command("show")
def skills_show(slug: str = typer.Argument(...)) -> None:
    """Mostra detalhes de uma skill."""
    import asyncio

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get(f"/api/v1/skills/{slug}")
            if resp.status_code == 404:
                console.print(f"[red]Skill '{slug}' não encontrada.[/red]")
                raise typer.Exit(1)
            resp.raise_for_status()
            data = resp.json()

        manifest = json.loads(data.get("manifest_json", "{}"))
        console.print(f"[bold]Slug:[/bold] {slug}")
        console.print(f"[bold]Status:[/bold] {data.get('status')}")
        console.print(f"[bold]Version:[/bold] {data.get('version')}")
        console.print(f"[bold]Descrição:[/bold] {manifest.get('description', '')}")
        console.print(f"[bold]Sandbox:[/bold] {manifest.get('sandbox_profile', '?')}")
        console.print(f"[bold]Irreversível:[/bold] {manifest.get('irreversible', False)}")
        console.print(f"[bold]Execuções:[/bold] {data.get('executions_count', 0)}")
        console.print(f"[bold]Sucesso:[/bold] {data.get('successes_count', 0)}")
        console.print(f"[bold]Falhas:[/bold] {data.get('failures_count', 0)}")
        console.print(f"[bold]Aprovação crítico:[/bold] {data.get('critic_approval_id', 'N/A')}")

    asyncio.run(_run())


@app.command("run")
def skills_run(
    slug: str = typer.Argument(...),
    input_json: str = typer.Option(..., "--input", "-i", help='Input JSON (ex: \'{"url":"..."}\')'),
    mission_id: str | None = typer.Option(None, "--mission-id"),
) -> None:
    """Executa uma skill com o input fornecido."""
    import asyncio

    try:
        input_data = json.loads(input_json)
    except json.JSONDecodeError as exc:
        console.print(f"[red]Input inválido: {exc}[/red]")
        raise typer.Exit(1)

    async def _run() -> None:
        payload: dict = {"input": input_data}
        if mission_id:
            payload["mission_id"] = mission_id
        async with _http() as client:
            resp = await client.post(f"/api/v1/skills/{slug}/run", json=payload)
            if resp.status_code != 200:
                console.print(f"[red]Erro: {resp.status_code} {resp.text}[/red]")
                raise typer.Exit(1)
            result = resp.json()

        console.print("[green]OK[/green]")
        console.print_json(json.dumps(result["output"]))
        console.print(
            f"execution_id={result['execution_id']} duration={result['duration_seconds']:.2f}s"
        )

    asyncio.run(_run())


@app.command("promote")
def skills_promote(
    slug: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Força promoção sem Crítico"),
) -> None:
    """Promove skill ao Crítico (ou força com --force)."""
    import asyncio

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/api/v1/skills/{slug}/promote", json={"force": force})
            resp.raise_for_status()
            result = resp.json()
        status = "aprovada" if result.get("approved") else "rejeitada"
        console.print(
            f"[{'green' if result.get('approved') else 'red'}]Skill '{slug}' {status}.[/{'green' if result.get('approved') else 'red'}]"
        )

    asyncio.run(_run())


@app.command("reject")
def skills_reject(
    slug: str = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", "-r", help="Motivo da rejeição"),
) -> None:
    """Rejeita uma skill com motivo."""
    import asyncio

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/api/v1/skills/{slug}/reject", json={"reason": reason})
            resp.raise_for_status()
        console.print(f"[yellow]Skill '{slug}' rejeitada: {reason}[/yellow]")

    asyncio.run(_run())


@app.command("archive")
def skills_archive(slug: str = typer.Argument(...)) -> None:
    """Arquiva (depreca) uma skill."""
    import asyncio

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post(f"/api/v1/skills/{slug}/archive")
            resp.raise_for_status()
        console.print(f"[dim]Skill '{slug}' arquivada.[/dim]")

    asyncio.run(_run())


@app.command("stats")
def skills_stats() -> None:
    """Tabela: slug, status, executions, success_rate, last_used."""
    import asyncio

    async def _run() -> None:
        async with _http() as client:
            resp = await client.get("/api/v1/skills/stats")
            resp.raise_for_status()
            rows = resp.json()

        if not rows:
            console.print("[yellow]Nenhuma skill registrada.[/yellow]")
            return

        table = Table(title="Estatísticas de Skills")
        table.add_column("Slug", style="cyan")
        table.add_column("Status")
        table.add_column("Execuções", justify="right")
        table.add_column("Taxa sucesso", justify="right")
        table.add_column("Último uso")
        for row in rows:
            rate = row.get("success_rate")
            rate_str = f"{rate:.1%}" if rate is not None else "—"
            table.add_row(
                row["slug"],
                row.get("status", "?"),
                str(row.get("executions_count", 0)),
                rate_str,
                str(row.get("last_used_at") or "nunca"),
            )
        console.print(table)

    asyncio.run(_run())


@app.command("synthesize")
def skills_synthesize(
    scan: bool = typer.Option(False, "--scan", help="Roda SkillSynthesizer.scan_for_candidates()"),
) -> None:
    """Dispara varredura manual do SkillSynthesizer."""
    import asyncio

    if not scan:
        console.print("[yellow]Use --scan para disparar a varredura.[/yellow]")
        raise typer.Exit(0)

    async def _run() -> None:
        async with _http() as client:
            resp = await client.post("/api/v1/skills/synthesize")
            resp.raise_for_status()
            result = resp.json()
        console.print(f"Clusters encontrados: {result.get('clusters_found', 0)}")
        if result.get("slugs"):
            console.print("Slugs: " + ", ".join(result["slugs"]))

    asyncio.run(_run())
