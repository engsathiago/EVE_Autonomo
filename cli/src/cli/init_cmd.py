"""
agent init — Wizard interativo de configuração inicial.

Inspirado no `claude init` (OpenClaw) e no `hermes setup` (Nous Research).
Guia o usuário pela escolha de provider, model, key, e grava o .env.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

app = typer.Typer(help="Setup interativo da EVE.")
console = Console()


PROVIDERS = {
    "1": {
        "id": "ollama-cloud",
        "label": "Ollama Cloud (recomendado — sem GPU, baixo custo)",
        "needs_key": True,
        "key_env": "OLLAMA_API_KEY",
        "key_url": "https://ollama.com/settings/keys",
        "base_url": "https://ollama.com",
        "models": [
            "ollama:gpt-oss:120b",
            "ollama:qwen3-coder:480b-cloud",
            "ollama:deepseek-v3.1:671b-cloud",
            "ollama:kimi-k2:1t-cloud",
        ],
        "default_model": "ollama:gpt-oss:120b",
    },
    "2": {
        "id": "ollama-local",
        "label": "Ollama Local (precisa GPU 8GB+, sem custo)",
        "needs_key": False,
        "key_env": None,
        "base_url": "http://localhost:11434",
        "models": [
            "ollama:qwen2.5:7b-instruct",
            "ollama:llama3.2:3b",
            "ollama:deepseek-r1:7b",
        ],
        "default_model": "ollama:qwen2.5:7b-instruct",
    },
    "3": {
        "id": "anthropic",
        "label": "Anthropic Claude (melhor qualidade, custo médio)",
        "needs_key": True,
        "key_env": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": [
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-6",
        ],
        "default_model": "anthropic:claude-haiku-4-5",
    },
    "4": {
        "id": "openai",
        "label": "OpenAI (GPT-4o)",
        "needs_key": True,
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": [
            "openai:gpt-4o",
            "openai:gpt-4o-mini",
        ],
        "default_model": "openai:gpt-4o-mini",
    },
    "5": {
        "id": "openrouter",
        "label": "OpenRouter (acesso a vários modelos via 1 chave)",
        "needs_key": True,
        "key_env": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys",
        "models": [
            "openrouter:deepseek/deepseek-chat",
            "openrouter:google/gemini-2.0-flash-exp",
            "openrouter:meta-llama/llama-3.3-70b-instruct",
        ],
        "default_model": "openrouter:deepseek/deepseek-chat",
    },
}


def _banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]EVE[/bold cyan] — Agente Autônomo\n"
        "[dim]Setup interativo (estilo OpenClaw / Hermes)[/dim]",
        border_style="cyan",
    ))


def _choose_provider() -> dict:
    table = Table(title="Escolha o provider de LLM", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Provider", style="white")
    table.add_column("Notas", style="dim")

    for key, p in PROVIDERS.items():
        notes = ""
        if p["needs_key"]:
            notes = f"requer key em {p.get('key_url', '')}"
        table.add_row(key, p["label"], notes)

    console.print(table)

    choice = Prompt.ask(
        "Escolha (1-5)",
        choices=list(PROVIDERS.keys()),
        default="1",
    )
    return PROVIDERS[choice]


def _choose_model(provider: dict) -> str:
    console.print(f"\n[bold]Modelos disponíveis para {provider['label']}:[/bold]")
    for i, m in enumerate(provider["models"], 1):
        marker = " [green](default)[/green]" if m == provider["default_model"] else ""
        console.print(f"  [cyan]{i}[/cyan]. {m}{marker}")

    choice = Prompt.ask(
        "Modelo padrão",
        default=provider["default_model"],
    )

    # Aceita número ou string completa
    if choice.isdigit() and 1 <= int(choice) <= len(provider["models"]):
        return provider["models"][int(choice) - 1]
    return choice


def _ask_api_key(provider: dict) -> str:
    console.print()
    console.print(f"[yellow]Obtenha sua chave em:[/yellow] {provider['key_url']}")
    key = Prompt.ask(
        f"Cole sua [bold]{provider['key_env']}[/bold]",
        password=True,
    )
    if not key.strip():
        console.print("[red]Chave vazia — cancelando setup.[/red]")
        raise typer.Exit(1)
    return key.strip()


def _ask_postgres() -> dict:
    console.print()
    console.print("[bold]Configuração de banco (PostgreSQL + pgvector):[/bold]")
    use_docker = Confirm.ask(
        "Vai usar Docker Compose? (recomendado)",
        default=True,
    )

    if use_docker:
        return {
            "host": "postgres",   # nome do serviço no docker-compose
            "user": "agent",
            "password": Prompt.ask("Senha do Postgres", default="changeme", password=True),
            "db": "agent",
        }
    else:
        return {
            "host": Prompt.ask("Host Postgres", default="localhost"),
            "user": Prompt.ask("Usuário Postgres", default="agent"),
            "password": Prompt.ask("Senha Postgres", password=True),
            "db": Prompt.ask("Database", default="agent"),
        }


def _write_env(env_path: Path, settings: dict) -> None:
    """Escreve ou atualiza o .env preservando linhas existentes não conflitantes."""
    lines: list[str] = []

    # Cabeçalho
    lines.append("# Gerado por `agent init` — pode editar manualmente")
    lines.append("")

    # Provider escolhido
    lines.append("# === Provider Principal ===")
    lines.append(f"DEFAULT_MODEL={settings['default_model']}")
    lines.append("")

    # Anthropic
    lines.append("# === Anthropic ===")
    lines.append(f"ANTHROPIC_API_KEY={settings.get('anthropic_key', '')}")
    lines.append("")

    # OpenAI
    lines.append("# === OpenAI ===")
    lines.append(f"OPENAI_API_KEY={settings.get('openai_key', '')}")
    lines.append("")

    # OpenRouter
    lines.append("# === OpenRouter ===")
    lines.append(f"OPENROUTER_API_KEY={settings.get('openrouter_key', '')}")
    lines.append("")

    # Ollama
    lines.append("# === Ollama (local OU cloud) ===")
    lines.append(f"OLLAMA_BASE_URL={settings.get('ollama_base_url', 'http://localhost:11434')}")
    lines.append(f"OLLAMA_API_KEY={settings.get('ollama_key', '')}")
    lines.append("")

    # Postgres
    pg = settings["postgres"]
    lines.append("# === Postgres ===")
    lines.append(f"POSTGRES_USER={pg['user']}")
    lines.append(f"POSTGRES_PASSWORD={pg['password']}")
    lines.append(f"POSTGRES_DB={pg['db']}")
    lines.append(f"POSTGRES_URL=postgresql://{pg['user']}:{pg['password']}@{pg['host']}:5432/{pg['db']}")
    lines.append("")

    # Redis
    lines.append("# === Redis ===")
    redis_host = "redis" if pg["host"] == "postgres" else "localhost"
    lines.append(f"REDIS_URL=redis://{redis_host}:6379/0")
    lines.append("")

    # Outros defaults
    lines.append("# === Defaults ===")
    lines.append("MODEL_TIMEOUT_S=60")
    lines.append("APPROVAL_DEFAULT_TIMEOUT_SECONDS=1800")
    lines.append("LOG_LEVEL=INFO")

    env_path.write_text("\n".join(lines) + "\n")


def _test_connection(provider: dict, key: str) -> bool:
    """Testa conexão com o provider escolhido."""
    import asyncio

    async def _test() -> bool:
        try:
            if provider["id"].startswith("ollama"):
                from agent.models.transports.ollama import OllamaTransport
                t = OllamaTransport(
                    base_url=provider.get("base_url", "http://localhost:11434"),
                    api_key=key if provider["needs_key"] else "",
                )
                status = await t.health()
                return status.ok
            elif provider["id"] == "anthropic":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    )
                    return r.status_code == 200
            elif provider["id"] == "openai":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    return r.status_code == 200
            elif provider["id"] == "openrouter":
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(
                        "https://openrouter.ai/api/v1/models",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    return r.status_code == 200
        except Exception as exc:
            console.print(f"[red]Erro: {exc}[/red]")
            return False
        return False

    return asyncio.run(_test())


@app.callback(invoke_without_command=True)
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Sobrescreve .env existente"),
    env_path_str: str = typer.Option(".env", "--env-path", help="Caminho do arquivo .env"),
) -> None:
    """Wizard interativo de configuração inicial — estilo OpenClaw/Hermes."""
    _banner()

    env_path = Path(env_path_str).resolve()

    if env_path.exists() and not force:
        if not Confirm.ask(
            f"\n[yellow]Já existe um {env_path.name}[/yellow] — sobrescrever?",
            default=False,
        ):
            console.print("[dim]Cancelado. Use --force para forçar.[/dim]")
            raise typer.Exit(0)

    settings: dict = {}

    # 1. Provider
    console.print()
    provider = _choose_provider()
    settings["provider_id"] = provider["id"]

    # 2. Model
    model = _choose_model(provider)
    settings["default_model"] = model

    # 3. API Key (se necessário)
    if provider["needs_key"]:
        key = _ask_api_key(provider)

        # 4. Testa conexão
        console.print("\n[dim]Testando conexão com o provider...[/dim]")
        if _test_connection(provider, key):
            console.print("[green]✓ Conexão OK[/green]")
        else:
            console.print("[red]✗ Falha na conexão.[/red]")
            if not Confirm.ask("Continuar mesmo assim?", default=False):
                raise typer.Exit(1)

        # Mapeia key para o env var correto
        key_var = {
            "ollama-cloud": "ollama_key",
            "anthropic": "anthropic_key",
            "openai": "openai_key",
            "openrouter": "openrouter_key",
        }.get(provider["id"])
        if key_var:
            settings[key_var] = key

    # Se cloud Ollama, seta base_url
    if provider["id"] == "ollama-cloud":
        settings["ollama_base_url"] = "https://ollama.com"

    # 5. Postgres
    settings["postgres"] = _ask_postgres()

    # 6. Resumo
    console.print()
    summary = Table(title="Resumo da Configuração", show_header=False, border_style="cyan")
    summary.add_column("Setting", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Provider", provider["label"])
    summary.add_row("Modelo padrão", settings["default_model"])
    summary.add_row("Postgres host", settings["postgres"]["host"])
    summary.add_row(".env path", str(env_path))
    console.print(summary)

    if not Confirm.ask("\n[bold]Gravar configuração?[/bold]", default=True):
        console.print("[dim]Cancelado.[/dim]")
        raise typer.Exit(0)

    # 7. Grava .env
    _write_env(env_path, settings)
    console.print(f"\n[green]✓ {env_path} criado[/green]")

    # 8. Próximos passos
    console.print()
    console.print(Panel(
        "[bold]Próximos passos:[/bold]\n\n"
        "  [cyan]1.[/cyan] Suba os serviços:\n"
        "     [dim]docker compose up --build -d[/dim]\n\n"
        "  [cyan]2.[/cyan] Valide a instalação:\n"
        "     [dim]agent doctor[/dim]\n\n"
        "  [cyan]3.[/cyan] Veja o status:\n"
        "     [dim]agent status[/dim]\n\n"
        "  [cyan]4.[/cyan] Converse com a EVE:\n"
        "     [dim]agent run \"Quem é você?\"[/dim]",
        title="Setup Concluído",
        border_style="green",
    ))
