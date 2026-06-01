"""
agent status — Dashboard de status (estilo Hermes Agent).

Mostra de uma só vez:
  - Provider e modelo ativo
  - Health do core
  - Health do banco e Redis
  - Health dos providers configurados
  - Estatísticas: missões, custos, aprovações pendentes
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Dashboard de status da EVE.")
console = Console()


@app.callback(invoke_without_command=True)
def status(
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Inclui últimas atividades"),
) -> None:
    """Mostra o status geral da EVE (estilo Hermes Agent)."""
    asyncio.run(_show_status(detailed))


async def _show_status(detailed: bool) -> None:

    # ─── 1. Carrega settings ────────────────────────────────────────
    try:
        from agent.config import get_settings

        settings = get_settings()
    except Exception as exc:
        console.print(f"[red]✗ Erro carregando config: {exc}[/red]")
        console.print("[dim]Rode: agent init[/dim]")
        raise typer.Exit(1)

    # ─── 2. Header ───────────────────────────────────────────────────
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]EVE[/bold cyan] — Agente Autônomo  [dim]| {settings.agent.name}[/dim]",
            border_style="cyan",
        )
    )

    # ─── 3. Configuração ativa ───────────────────────────────────────
    config_table = Table(show_header=False, border_style="cyan")
    config_table.add_column("Setting", style="cyan", width=20)
    config_table.add_column("Value", style="white")
    config_table.add_row("Modelo padrão", settings.models.default_model)
    config_table.add_row("Fallback chain", settings.models.fallback_chain or "[dim]nenhum[/dim]")
    config_table.add_row("Timeout (s)", str(settings.models.timeout_s))
    config_table.add_row("Max iterations", str(settings.agent.max_iterations))
    config_table.add_row("Loop autônomo", "✓ ativo" if settings.missions.loop_enabled else "✗ desativado")
    console.print(Panel(config_table, title="Configuração Ativa", border_style="cyan"))

    # ─── 4. Health da infra ──────────────────────────────────────────
    infra_table = Table(show_header=True, border_style="yellow")
    infra_table.add_column("Service", style="yellow")
    infra_table.add_column("Status", style="white")
    infra_table.add_column("Latência", style="dim")

    # Postgres
    pg_status, pg_latency = await _check_postgres(settings)
    infra_table.add_row("PostgreSQL", pg_status, pg_latency)

    # Redis
    redis_status, redis_latency = await _check_redis(settings)
    infra_table.add_row("Redis", redis_status, redis_latency)

    # Core HTTP
    core_status, core_latency = await _check_core_http()
    infra_table.add_row("Core HTTP", core_status, core_latency)

    # Gateway HTTP
    gw_status, gw_latency = await _check_gateway_http()
    infra_table.add_row("Gateway HTTP", gw_status, gw_latency)

    console.print(Panel(infra_table, title="Infraestrutura", border_style="yellow"))

    # ─── 5. Providers de LLM ─────────────────────────────────────────
    providers_table = Table(show_header=True, border_style="magenta")
    providers_table.add_column("Provider", style="magenta")
    providers_table.add_column("Status", style="white")
    providers_table.add_column("Notas", style="dim")

    for label, status_str, notes in await _check_providers(settings):
        providers_table.add_row(label, status_str, notes)

    console.print(Panel(providers_table, title="Providers de LLM", border_style="magenta"))

    # ─── 6. Estatísticas (se DB disponível) ──────────────────────────
    if pg_status == "[green]✓[/green]":
        stats = await _gather_stats(settings)
        if stats:
            stats_table = Table(show_header=False, border_style="green")
            stats_table.add_column("Métrica", style="green")
            stats_table.add_column("Valor", style="white")
            for k, v in stats.items():
                stats_table.add_row(k, str(v))
            console.print(Panel(stats_table, title="Estatísticas (24h)", border_style="green"))

    # ─── 7. Últimas atividades ───────────────────────────────────────
    if detailed and pg_status == "[green]✓[/green]":
        await _show_recent(settings)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


async def _check_postgres(settings) -> tuple[str, str]:
    import time

    try:
        import asyncpg

        t0 = time.monotonic()
        conn = await asyncpg.connect(
            os.environ.get("POSTGRES_URL", settings.redis.url.replace("redis", "postgres")),
            timeout=3,
        )
        await conn.fetchval("SELECT 1")
        await conn.close()
        ms = int((time.monotonic() - t0) * 1000)
        return "[green]✓[/green]", f"{ms}ms"
    except Exception as exc:
        return "[red]✗[/red]", f"{type(exc).__name__}"


async def _check_redis(settings) -> tuple[str, str]:
    import time

    try:
        import redis.asyncio as aioredis

        t0 = time.monotonic()
        client = aioredis.from_url(settings.redis.url, socket_timeout=3)
        await client.ping()
        await client.aclose()
        ms = int((time.monotonic() - t0) * 1000)
        return "[green]✓[/green]", f"{ms}ms"
    except Exception as exc:
        return "[red]✗[/red]", f"{type(exc).__name__}"


async def _check_core_http() -> tuple[str, str]:
    import time

    import httpx

    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:8000/health")
            ms = int((time.monotonic() - t0) * 1000)
            if r.status_code == 200:
                return "[green]✓[/green]", f"{ms}ms"
            return "[yellow]?[/yellow]", f"HTTP {r.status_code}"
    except Exception:
        return "[dim]offline[/dim]", "—"


async def _check_gateway_http() -> tuple[str, str]:
    import time

    import httpx

    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://localhost:3000/health")
            ms = int((time.monotonic() - t0) * 1000)
            if r.status_code == 200:
                return "[green]✓[/green]", f"{ms}ms"
            return "[yellow]?[/yellow]", f"HTTP {r.status_code}"
    except Exception:
        return "[dim]offline[/dim]", "—"


async def _check_providers(settings) -> list[tuple[str, str, str]]:
    """Verifica health de cada provider configurado."""
    results: list[tuple[str, str, str]] = []

    # Ollama
    from agent.models.transports.ollama import OllamaTransport

    is_cloud = bool(settings.ollama.api_key)
    label = "Ollama Cloud" if is_cloud else "Ollama Local"
    try:
        t = OllamaTransport(
            base_url=settings.ollama.base_url,
            api_key=settings.ollama.api_key,
        )
        health = await t.health()
        if health.ok:
            results.append((label, "[green]✓[/green]", f"{health.models_loaded} modelos · {health.latency_ms}ms"))
        else:
            results.append((label, "[red]✗[/red]", health.message or ""))
    except Exception as exc:
        results.append((label, "[red]✗[/red]", str(exc)[:50]))

    # Anthropic
    if settings.anthropic.api_key:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": settings.anthropic.api_key, "anthropic-version": "2023-06-01"},
                )
                if r.status_code == 200:
                    results.append(("Anthropic", "[green]✓[/green]", "API respondendo"))
                else:
                    results.append(("Anthropic", "[red]✗[/red]", f"HTTP {r.status_code}"))
        except Exception as exc:
            results.append(("Anthropic", "[red]✗[/red]", str(exc)[:50]))
    else:
        results.append(("Anthropic", "[dim]—[/dim]", "key não configurada"))

    # OpenAI
    if settings.openai.api_key:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.openai.api_key}"},
                )
                if r.status_code == 200:
                    results.append(("OpenAI", "[green]✓[/green]", "API respondendo"))
                else:
                    results.append(("OpenAI", "[red]✗[/red]", f"HTTP {r.status_code}"))
        except Exception as exc:
            results.append(("OpenAI", "[red]✗[/red]", str(exc)[:50]))
    else:
        results.append(("OpenAI", "[dim]—[/dim]", "key não configurada"))

    # OpenRouter
    if settings.openrouter.api_key:
        results.append(("OpenRouter", "[green]✓[/green]", "key configurada"))
    else:
        results.append(("OpenRouter", "[dim]—[/dim]", "key não configurada"))

    return results


async def _gather_stats(settings) -> dict[str, str]:
    """Coleta estatísticas do banco (últimas 24h)."""
    try:
        import asyncpg

        conn = await asyncpg.connect(
            os.environ.get("POSTGRES_URL", ""),
            timeout=3,
        )
        try:
            since = datetime.utcnow() - timedelta(hours=24)
            stats = {}

            # Mensagens
            try:
                count = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE created_at >= $1", since)
                stats["Mensagens"] = f"{count or 0}"
            except Exception:
                pass

            # Tokens
            try:
                row = await conn.fetchrow(
                    "SELECT SUM(input_tokens) as inp, SUM(output_tokens) as out, "
                    "SUM(cost_usd) as cost FROM model_invocations WHERE created_at >= $1",
                    since,
                )
                if row:
                    inp = row["inp"] or 0
                    out = row["out"] or 0
                    cost = float(row["cost"] or 0)
                    stats["Tokens entrada"] = f"{inp:,}"
                    stats["Tokens saída"] = f"{out:,}"
                    stats["Custo (USD)"] = f"${cost:.4f}"
            except Exception:
                pass

            # Missões ativas
            try:
                active = await conn.fetchval("SELECT COUNT(*) FROM missions WHERE status = 'active'")
                stats["Missões ativas"] = f"{active or 0}"
            except Exception:
                pass

            # Aprovações pendentes
            try:
                pending = await conn.fetchval("SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'")
                stats["Aprovações pendentes"] = f"{pending or 0}"
            except Exception:
                pass

            return stats
        finally:
            await conn.close()
    except Exception:
        return {}


async def _show_recent(settings) -> None:
    """Mostra últimas atividades quando --detailed."""
    try:
        import asyncpg

        conn = await asyncpg.connect(
            os.environ.get("POSTGRES_URL", ""),
            timeout=3,
        )
        try:
            # Últimas 5 chamadas LLM
            rows = await conn.fetch(
                "SELECT model_id, input_tokens, output_tokens, cost_usd, created_at "
                "FROM model_invocations ORDER BY created_at DESC LIMIT 5"
            )
            if rows:
                table = Table(title="Últimas Chamadas LLM", show_header=True)
                table.add_column("Quando", style="dim")
                table.add_column("Modelo", style="cyan")
                table.add_column("Tokens", style="white")
                table.add_column("Custo", style="green")
                for r in rows:
                    when = r["created_at"].strftime("%H:%M:%S")
                    tok = f"{r['input_tokens']}+{r['output_tokens']}"
                    cost = f"${float(r['cost_usd'] or 0):.4f}"
                    table.add_row(when, r["model_id"], tok, cost)
                console.print(table)
        finally:
            await conn.close()
    except Exception:
        pass
