"""
Subcomando `agent model` — lista, health check, detalhes e custos.
"""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Gerencia providers e modelos LLM.")
console = Console()


def _get_router() -> Any:
    from agent.config import build_model_router, get_settings

    return build_model_router(get_settings())


# ---------------------------------------------------------------------------
# agent model list
# ---------------------------------------------------------------------------


@app.command("list")
def model_list() -> None:
    """Lista todos os modelos disponíveis (cloud hardcoded + Ollama via /api/tags)."""
    from agent.observability import configure_logging

    configure_logging("WARNING")

    async def _run() -> None:
        router = _get_router()
        models = await router.list_all_models()
        if not models:
            console.print("[yellow]Nenhum modelo disponível. Verifique as API keys e o Ollama.[/yellow]")
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("PROVIDER", style="dim")
        table.add_column("MODEL")
        table.add_column("CTX", justify="right")
        table.add_column("TOOL", justify="center")
        table.add_column("VISION", justify="center")
        table.add_column("COST IN", justify="right")
        table.add_column("COST OUT", justify="right")

        for m in sorted(models, key=lambda x: (x.provider, x.model_id)):
            ctx = f"{m.capabilities.max_context // 1000}k"
            tool = "✓" if m.capabilities.tool_use else "✗"
            vision = "✓" if m.capabilities.vision else "✗"
            cost_in = f"${m.cost_input_per_1m:.2f}" if m.cost_input_per_1m else "$0"
            cost_out = f"${m.cost_output_per_1m:.2f}" if m.cost_output_per_1m else "$0"
            table.add_row(m.provider, m.model_id, ctx, tool, vision, cost_in, cost_out)

        console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# agent model health
# ---------------------------------------------------------------------------


@app.command("health")
def model_health() -> None:
    """Health check de todos os providers configurados."""
    from agent.observability import configure_logging

    configure_logging("WARNING")

    async def _run() -> None:
        router = _get_router()
        statuses = await router.health_all()
        if not statuses:
            console.print("[yellow]Nenhum provider registrado.[/yellow]")
            return

        for name, status in sorted(statuses.items()):
            if status.ok:
                extra = f"({status.latency_ms}ms)"
                if status.models_loaded:
                    extra += f" — {status.models_loaded} modelo(s) carregado(s)"
                console.print(f"[green]✓[/green] {name:<14} ok {extra}")
            else:
                console.print(f"[red]✗[/red] {name:<14} {status.message}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# agent model show
# ---------------------------------------------------------------------------


@app.command("show")
def model_show(model_alias: str = typer.Argument(..., help="ex: ollama:qwen2.5:7b")) -> None:
    """Exibe detalhes de capabilities de um modelo."""
    from agent.observability import configure_logging

    configure_logging("WARNING")

    async def _run() -> None:
        from agent.models.router import parse_model_string

        try:
            provider, model_id = parse_model_string(model_alias)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        router = _get_router()
        all_models = await router.list_all_models()
        matches = [
            m for m in all_models if m.alias == model_alias or (m.provider == provider and m.model_id == model_id)
        ]

        if not matches:
            console.print(f"[yellow]Modelo '{model_alias}' não encontrado nos providers ativos.[/yellow]")
            raise typer.Exit(1)

        m = matches[0]
        caps = m.capabilities
        console.print(f"\n[bold]{m.alias}[/bold]")
        console.print(f"  Provider:      {m.provider}")
        console.print(f"  Model ID:      {m.model_id}")
        console.print(f"  Context:       {caps.max_context:,} tokens")
        console.print(f"  Tool use:      {'✓' if caps.tool_use else '✗'}")
        console.print(f"  Vision:        {'✓' if caps.vision else '✗'}")
        console.print(f"  JSON mode:     {'✓' if caps.json_mode else '✗'}")
        console.print(f"  Streaming:     {'✓' if caps.streaming else '✗'}")
        console.print(f"  Parallel tools:{'✓' if caps.parallel_tools else '✗'}")
        if m.cost_input_per_1m:
            console.print(f"  Cost (input):  ${m.cost_input_per_1m}/1M tokens")
            console.print(f"  Cost (output): ${m.cost_output_per_1m}/1M tokens")
        else:
            console.print("  Cost:          $0 (local)")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# agent model test
# ---------------------------------------------------------------------------


@app.command("test")
def model_test(
    model_alias: str = typer.Argument(..., help="ex: anthropic:claude-haiku-4-5"),
) -> None:
    """Envia 'ping' ao modelo e exibe resposta, latência e custo."""
    from agent.observability import configure_logging

    configure_logging("WARNING")

    async def _run() -> None:
        import time

        from agent.models.base import Message
        from agent.models.router import parse_model_string

        try:
            provider, model_id = parse_model_string(model_alias)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

        router = _get_router()
        console.print(f"Testando [bold]{model_alias}[/bold]...")

        t0 = time.monotonic()
        try:
            resp = await router.chat_unified(
                model_alias=model_alias,
                messages=[Message(role="user", content="Responda apenas com a palavra 'pong'.")],
                max_tokens=32,
            )
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            raise typer.Exit(1)

        latency_ms = int((time.monotonic() - t0) * 1000)
        from agent.models.pricing import cost_usd

        c = cost_usd(model_alias, resp.usage.input_tokens, resp.usage.output_tokens, resp.openrouter_cost_usd)

        console.print(f"  Resposta:  [green]{resp.text.strip()!r}[/green]")
        console.print(f"  Latência:  {latency_ms}ms")
        console.print(f"  Tokens:    {resp.usage.input_tokens} in / {resp.usage.output_tokens} out")
        console.print(f"  Custo:     ${c}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# agent model costs
# ---------------------------------------------------------------------------


@app.command("costs")
def model_costs(
    since: str = typer.Option("today", help="'today', 'week', ou data ISO 'YYYY-MM-DD'"),
) -> None:
    """Exibe consumo e custo agregado por modelo."""
    from agent.observability import configure_logging

    configure_logging("WARNING")

    async def _run() -> None:
        from datetime import date, datetime, timedelta

        import asyncpg

        # Resolve período
        today = date.today()
        if since == "today":
            since_dt = datetime.combine(today, datetime.min.time())
        elif since == "week":
            since_dt = datetime.combine(today - timedelta(days=7), datetime.min.time())
        else:
            try:
                since_dt = datetime.fromisoformat(since)
            except ValueError:
                console.print(f"[red]Data inválida: {since!r}. Use 'today', 'week' ou 'YYYY-MM-DD'.[/red]")
                raise typer.Exit(1)

        dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("POSTGRES_URL")
        if not dsn:
            console.print("[red]POSTGRES_DSN não configurado.[/red]")
            raise typer.Exit(1)

        try:
            conn = await asyncpg.connect(dsn)
        except Exception as exc:
            console.print(f"[red]Não foi possível conectar ao banco: {exc}[/red]")
            raise typer.Exit(1)

        rows = await conn.fetch(
            """
            SELECT
                provider || ':' || model AS model_alias,
                COUNT(*) AS calls,
                SUM(total_tokens) AS tokens,
                SUM(cost_usd) AS cost_usd,
                SUM(CASE WHEN fallback_used THEN 1 ELSE 0 END) AS fallbacks
            FROM model_invocations
            WHERE started_at >= $1
            GROUP BY provider, model
            ORDER BY cost_usd DESC
            """,
            since_dt,
        )
        await conn.close()

        if not rows:
            console.print("[dim]Nenhuma invocação no período.[/dim]")
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("MODEL")
        table.add_column("CALLS", justify="right")
        table.add_column("TOKENS", justify="right")
        table.add_column("COST USD", justify="right")
        table.add_column("FALLBACKS", justify="right")

        total_calls = total_tokens = total_cost = 0
        for row in rows:
            table.add_row(
                row["model_alias"],
                str(row["calls"]),
                f"{row['tokens']:,}" if row["tokens"] else "0",
                f"${float(row['cost_usd']):.4f}",
                str(row["fallbacks"]),
            )
            total_calls += row["calls"]
            total_tokens += row["tokens"] or 0
            total_cost += float(row["cost_usd"] or 0)

        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]{total_calls}[/bold]",
            f"[bold]{total_tokens:,}[/bold]",
            f"[bold]${total_cost:.4f}[/bold]",
            "",
        )
        console.print(table)

    asyncio.run(_run())


# Alias de importação para type hints
from typing import Any
