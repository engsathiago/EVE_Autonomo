"""
agent config — Gerenciamento de configuração estilo OpenClaw.

Subcomandos:
  agent config show              Mostra configuração atual
  agent config use <model>       Define modelo padrão
  agent config set <key> <value> Define qualquer variável no .env
  agent config models            Lista modelos disponíveis em todos os providers
  agent config providers         Lista providers configurados
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Gerencia configuração da EVE (estilo OpenClaw).")
console = Console()


# ---------------------------------------------------------------------------
# helpers: ler/escrever .env preservando comentários e ordem
# ---------------------------------------------------------------------------

def _env_path() -> Path:
    return Path(os.environ.get("ENV_PATH", ".env")).resolve()


def _read_env(path: Path | None = None) -> dict[str, str]:
    """Lê .env como dict, preservando comentários."""
    path = path or _env_path()
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env_key(key: str, value: str, path: Path | None = None) -> None:
    """Atualiza ou adiciona uma key no .env preservando o resto."""
    path = path or _env_path()
    if not path.exists():
        path.write_text(f"{key}={value}\n")
        return

    lines = path.read_text().splitlines()
    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    found = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            found = True
            break

    if not found:
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n")


def _mask(value: str, keep: int = 4) -> str:
    """Mascara valores sensíveis (api keys)."""
    if not value:
        return "[dim]<vazio>[/dim]"
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}...{value[-keep:]}"


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

@app.command()
def show() -> None:
    """Mostra a configuração atual (api keys mascaradas)."""
    env = _read_env()
    path = _env_path()

    if not env:
        console.print(f"[yellow]Nenhum .env encontrado em {path}[/yellow]")
        console.print("[dim]Rode: agent init[/dim]")
        raise typer.Exit(1)

    # Provider info
    table_provider = Table(title="Provider Atual", show_header=False, border_style="cyan")
    table_provider.add_column("Key", style="cyan")
    table_provider.add_column("Value", style="white")
    table_provider.add_row("Modelo padrão", env.get("DEFAULT_MODEL", "[dim]não definido[/dim]"))
    table_provider.add_row("Fallback chain", env.get("MODEL_FALLBACK_CHAIN", "[dim]nenhum[/dim]"))
    table_provider.add_row("Timeout (s)", env.get("MODEL_TIMEOUT_S", "60"))
    console.print(table_provider)

    # API keys
    table_keys = Table(title="API Keys", show_header=True, border_style="magenta")
    table_keys.add_column("Provider", style="cyan")
    table_keys.add_column("Configurado", style="green")
    table_keys.add_column("Valor (mascarado)", style="dim")

    providers = [
        ("Anthropic", "ANTHROPIC_API_KEY"),
        ("OpenAI", "OPENAI_API_KEY"),
        ("OpenRouter", "OPENROUTER_API_KEY"),
        ("Ollama Cloud", "OLLAMA_API_KEY"),
    ]
    for label, key in providers:
        value = env.get(key, "")
        status = "[green]✓[/green]" if value else "[red]✗[/red]"
        table_keys.add_row(label, status, _mask(value))
    console.print(table_keys)

    # Infra
    table_infra = Table(title="Infra", show_header=False, border_style="yellow")
    table_infra.add_column("Service", style="yellow")
    table_infra.add_column("URL", style="dim")
    table_infra.add_row("Postgres", env.get("POSTGRES_URL", "[dim]não definido[/dim]"))
    table_infra.add_row("Redis", env.get("REDIS_URL", "[dim]não definido[/dim]"))
    table_infra.add_row("Ollama base", env.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    console.print(table_infra)

    # Canais
    table_channels = Table(title="Canais", show_header=True, border_style="blue")
    table_channels.add_column("Canal", style="blue")
    table_channels.add_column("Status", style="white")
    channels = [
        ("Telegram", "TELEGRAM_BOT_TOKEN"),
        ("Discord", "DISCORD_BOT_TOKEN"),
        ("Slack", "SLACK_BOT_TOKEN"),
        ("E-mail", "EMAIL_USER"),
    ]
    for label, key in channels:
        status = "[green]✓ configurado[/green]" if env.get(key) else "[dim]não configurado[/dim]"
        table_channels.add_row(label, status)
    console.print(table_channels)


# ---------------------------------------------------------------------------
# use <model>
# ---------------------------------------------------------------------------

@app.command()
def use(
    model: str = typer.Argument(..., help="ex: ollama:gpt-oss:120b, anthropic:claude-haiku-4-5"),
) -> None:
    """Define o modelo padrão (atualiza DEFAULT_MODEL no .env)."""
    # Validação básica
    if ":" not in model:
        console.print(f"[red]Formato inválido. Use provider:model_id (ex: anthropic:claude-haiku-4-5)[/red]")
        raise typer.Exit(1)

    provider = model.split(":")[0]
    valid = {"anthropic", "openai", "openrouter", "ollama"}
    if provider not in valid:
        console.print(f"[red]Provider inválido: {provider}. Use um de: {', '.join(valid)}[/red]")
        raise typer.Exit(1)

    _write_env_key("DEFAULT_MODEL", model)
    console.print(f"[green]✓[/green] Modelo padrão atualizado: [cyan]{model}[/cyan]")
    console.print("[dim]Reinicie o core para aplicar: docker compose restart core[/dim]")


# ---------------------------------------------------------------------------
# set <key> <value>
# ---------------------------------------------------------------------------

@app.command()
def set(
    key: str = typer.Argument(..., help="Nome da variável (ex: MODEL_TIMEOUT_S)"),
    value: str = typer.Argument(..., help="Novo valor"),
) -> None:
    """Define qualquer variável no .env (cuidado com chaves sensíveis!)."""
    # Aviso se for sensível
    sensitive = ("KEY", "TOKEN", "PASSWORD", "SECRET")
    is_sensitive = any(s in key.upper() for s in sensitive)

    _write_env_key(key, value)

    if is_sensitive:
        console.print(f"[green]✓[/green] [cyan]{key}[/cyan] = [dim]{_mask(value)}[/dim]")
    else:
        console.print(f"[green]✓[/green] [cyan]{key}[/cyan] = [yellow]{value}[/yellow]")


# ---------------------------------------------------------------------------
# get <key>
# ---------------------------------------------------------------------------

@app.command()
def get(
    key: str = typer.Argument(..., help="Nome da variável"),
) -> None:
    """Lê o valor de uma variável do .env."""
    env = _read_env()
    if key not in env:
        console.print(f"[red]{key} não encontrada[/red]")
        raise typer.Exit(1)

    sensitive = ("KEY", "TOKEN", "PASSWORD", "SECRET")
    is_sensitive = any(s in key.upper() for s in sensitive)

    value = env[key]
    if is_sensitive:
        console.print(f"{key}={_mask(value)} [dim](valor real omitido por segurança)[/dim]")
    else:
        console.print(f"{key}={value}")


# ---------------------------------------------------------------------------
# models — lista modelos disponíveis em todos os providers
# ---------------------------------------------------------------------------

@app.command()
def models() -> None:
    """Lista modelos disponíveis em cada provider configurado."""

    async def _list_all() -> None:
        env = _read_env()

        from agent.models.transports.ollama import OllamaTransport

        # Ollama (local ou cloud)
        ollama_url = env.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_key = env.get("OLLAMA_API_KEY", "")
        is_cloud = bool(ollama_key)

        console.print(f"\n[bold cyan]Ollama[/bold cyan] {'(Cloud)' if is_cloud else '(Local)'}")
        try:
            t = OllamaTransport(base_url=ollama_url, api_key=ollama_key)
            ollama_models = await t.list_models()
            if ollama_models:
                table = Table(show_header=True)
                table.add_column("Model", style="cyan")
                table.add_column("Context", style="dim")
                for m in ollama_models:
                    ctx = f"{m.capabilities.max_context:,}" if m.capabilities else "?"
                    table.add_row(f"ollama:{m.model_id}", ctx)
                console.print(table)
            else:
                console.print(f"  [yellow]Nenhum modelo (Ollama não respondeu em {ollama_url})[/yellow]")
        except Exception as exc:
            console.print(f"  [red]Erro: {exc}[/red]")

        # Anthropic (catálogo fixo — API não tem endpoint público de listing)
        if env.get("ANTHROPIC_API_KEY"):
            console.print("\n[bold cyan]Anthropic[/bold cyan]")
            table = Table(show_header=True)
            table.add_column("Model", style="cyan")
            table.add_column("Use", style="dim")
            for m, use in [
                ("claude-haiku-4-5", "rápido, barato"),
                ("claude-sonnet-4-6", "qualidade alta"),
                ("claude-opus-4-7", "máxima qualidade"),
            ]:
                table.add_row(f"anthropic:{m}", use)
            console.print(table)

        # OpenAI
        if env.get("OPENAI_API_KEY"):
            console.print("\n[bold cyan]OpenAI[/bold cyan]")
            table = Table(show_header=True)
            table.add_column("Model", style="cyan")
            table.add_column("Use", style="dim")
            for m, use in [
                ("gpt-4o-mini", "rápido, barato"),
                ("gpt-4o", "qualidade alta"),
                ("o1-mini", "reasoning"),
            ]:
                table.add_row(f"openai:{m}", use)
            console.print(table)

        # OpenRouter
        if env.get("OPENROUTER_API_KEY"):
            console.print("\n[bold cyan]OpenRouter[/bold cyan]")
            console.print("  [dim]Veja catálogo completo: https://openrouter.ai/models[/dim]")

    asyncio.run(_list_all())


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

@app.command()
def providers() -> None:
    """Lista providers configurados (alias visual)."""
    env = _read_env()

    table = Table(title="Providers Configurados", show_header=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Notas", style="dim")

    providers_info = [
        ("Anthropic", "ANTHROPIC_API_KEY", "anthropic:claude-haiku-4-5"),
        ("OpenAI", "OPENAI_API_KEY", "openai:gpt-4o-mini"),
        ("OpenRouter", "OPENROUTER_API_KEY", "openrouter:..."),
        ("Ollama Local", None, "ollama:qwen2.5:7b"),
        ("Ollama Cloud", "OLLAMA_API_KEY", "ollama:gpt-oss:120b"),
    ]

    default = env.get("DEFAULT_MODEL", "")

    for label, key, example in providers_info:
        if key is None:
            # Ollama local sempre disponível em teoria
            status = "[green]✓[/green]" if not env.get("OLLAMA_API_KEY") else "[dim]substituído pela cloud[/dim]"
        else:
            status = "[green]✓[/green]" if env.get(key) else "[red]✗[/red]"

        is_default = default.startswith(example.split(":")[0])
        notes = "[yellow]← em uso[/yellow]" if is_default and "✓" in status else ""
        table.add_row(label, status, notes)

    console.print(table)
    console.print(f"\n[dim]Trocar default: agent config use <provider>:<model>[/dim]")
