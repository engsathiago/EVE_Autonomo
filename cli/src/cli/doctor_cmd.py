"""
agent doctor — Diagnóstico completo da instalação.

Roda uma bateria de checks e reporta o que está OK e o que precisa de ajuste.
Inspirado em `brew doctor` e `npx create-react-app --doctor`.

Exit code 0 = tudo OK, 1 = problemas encontrados.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def doctor() -> None:
    """Valida a instalação da EVE e reporta problemas."""
    asyncio.run(_run_diagnostics())


# ---------------------------------------------------------------------------
# Diagnósticos
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, name: str, ok: bool, message: str = "", hint: str = ""):
        self.name = name
        self.ok = ok
        self.message = message
        self.hint = hint


async def _run_diagnostics() -> None:
    console.print()
    console.print("[bold cyan]EVE Doctor[/bold cyan] — validando instalação...\n")

    checks: list[CheckResult] = []

    # ─── 1. Python ────────────────────────────────────────────────
    checks.append(_check_python())

    # ─── 2. .env existe ────────────────────────────────────────────
    checks.append(_check_env_file())

    # ─── 3. Config carrega ────────────────────────────────────────
    settings, c = _check_config_loads()
    checks.append(c)

    if settings:
        # ─── 4. Pelo menos um provider configurado ─────────────────
        checks.append(_check_at_least_one_provider(settings))

        # ─── 5. Default model é válido ─────────────────────────────
        checks.append(_check_default_model(settings))

        # ─── 6. Postgres conecta ───────────────────────────────────
        checks.append(await _check_postgres(settings))

        # ─── 7. Redis conecta ──────────────────────────────────────
        checks.append(await _check_redis(settings))

        # ─── 8. Provider escolhido responde ────────────────────────
        checks.append(await _check_active_provider(settings))

        # ─── 9. Migrações aplicadas ────────────────────────────────
        checks.append(await _check_migrations(settings))

    # ─── 10. Docker (opcional) ─────────────────────────────────────
    checks.append(_check_docker())

    # ─── 11. Permissões em workspace ───────────────────────────────
    if settings:
        checks.append(_check_workspace_paths(settings))

    # ─── Relatório final ───────────────────────────────────────────
    console.print()
    passed = sum(1 for c in checks if c.ok)
    failed = len(checks) - passed

    for c in checks:
        icon = "[green]✓[/green]" if c.ok else "[red]✗[/red]"
        console.print(f"  {icon} [bold]{c.name}[/bold]: {c.message}")
        if not c.ok and c.hint:
            console.print(f"     [dim]→ {c.hint}[/dim]")

    console.print()
    if failed == 0:
        console.print(f"[bold green]Tudo OK![/bold green] {passed}/{len(checks)} checks passaram.")
        sys.exit(0)
    else:
        console.print(
            f"[bold yellow]{failed} problema(s) encontrado(s).[/bold yellow] "
            f"({passed}/{len(checks)} checks passaram)"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Checks individuais
# ---------------------------------------------------------------------------

def _check_python() -> CheckResult:
    v = sys.version_info
    if v.major == 3 and v.minor >= 11:
        return CheckResult("Python", True, f"{v.major}.{v.minor}.{v.micro}")
    return CheckResult(
        "Python", False, f"versão {v.major}.{v.minor} — requer 3.11+",
        hint="Instale Python 3.11 ou superior",
    )


def _check_env_file() -> CheckResult:
    env_path = Path(os.environ.get("ENV_PATH", ".env"))
    if env_path.exists():
        return CheckResult(".env", True, str(env_path.resolve()))
    return CheckResult(
        ".env", False, "arquivo não encontrado",
        hint="Rode `agent init` para criar",
    )


def _check_config_loads() -> tuple[object | None, CheckResult]:
    try:
        from agent.config import get_settings
        settings = get_settings()
        return settings, CheckResult("Config", True, "carregado com sucesso")
    except Exception as exc:
        return None, CheckResult(
            "Config", False, f"falha ao carregar: {exc}",
            hint="Verifique sintaxe do config.yaml e .env",
        )


def _check_at_least_one_provider(settings) -> CheckResult:
    providers_configured = []
    if settings.anthropic.api_key:
        providers_configured.append("anthropic")
    if settings.openai.api_key:
        providers_configured.append("openai")
    if settings.openrouter.api_key:
        providers_configured.append("openrouter")
    if settings.ollama.api_key or settings.ollama.base_url:
        providers_configured.append("ollama")

    if providers_configured:
        return CheckResult(
            "Provider LLM", True,
            f"{len(providers_configured)} configurado(s): {', '.join(providers_configured)}",
        )
    return CheckResult(
        "Provider LLM", False, "nenhum provider configurado",
        hint="Configure pelo menos uma API key (ANTHROPIC_API_KEY, OPENAI_API_KEY, OLLAMA_API_KEY, etc.)",
    )


def _check_default_model(settings) -> CheckResult:
    model = settings.models.default_model
    if ":" not in model:
        return CheckResult(
            "DEFAULT_MODEL", False, f"formato inválido: {model}",
            hint="Use o formato provider:model_id (ex: anthropic:claude-haiku-4-5)",
        )

    provider = model.split(":")[0]
    valid = {"anthropic", "openai", "openrouter", "ollama"}
    if provider not in valid:
        return CheckResult(
            "DEFAULT_MODEL", False, f"provider desconhecido: {provider}",
            hint=f"Providers válidos: {', '.join(valid)}",
        )

    # Verifica se a key correspondente está setada
    key_map = {
        "anthropic": settings.anthropic.api_key,
        "openai": settings.openai.api_key,
        "openrouter": settings.openrouter.api_key,
        "ollama": settings.ollama.api_key or True,  # Ollama local não precisa key
    }
    if not key_map.get(provider):
        return CheckResult(
            "DEFAULT_MODEL", False,
            f"modelo é {model} mas {provider.upper()}_API_KEY não está configurada",
            hint=f"Configure a key ou troque o default: agent config use <outro_modelo>",
        )

    return CheckResult("DEFAULT_MODEL", True, model)


async def _check_postgres(settings) -> CheckResult:
    try:
        import asyncpg
        url = os.environ.get("POSTGRES_URL", "")
        if not url:
            return CheckResult(
                "Postgres", False, "POSTGRES_URL não definido",
                hint="Defina POSTGRES_URL no .env",
            )
        conn = await asyncpg.connect(url, timeout=5)
        version = await conn.fetchval("SHOW server_version")
        await conn.close()
        return CheckResult("Postgres", True, f"conectado (v{version.split()[0]})")
    except Exception as exc:
        return CheckResult(
            "Postgres", False, f"falhou: {type(exc).__name__}",
            hint="Suba o Postgres: `docker compose up postgres -d` ou inicie manualmente",
        )


async def _check_redis(settings) -> CheckResult:
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis.url, socket_timeout=5)
        await client.ping()
        await client.aclose()
        return CheckResult("Redis", True, f"conectado em {settings.redis.url}")
    except Exception as exc:
        return CheckResult(
            "Redis", False, f"falhou: {type(exc).__name__}",
            hint="Suba o Redis: `docker compose up redis -d` ou inicie manualmente",
        )


async def _check_active_provider(settings) -> CheckResult:
    model = settings.models.default_model
    provider = model.split(":")[0] if ":" in model else ""

    if provider == "ollama":
        from agent.models.transports.ollama import OllamaTransport
        try:
            t = OllamaTransport(
                base_url=settings.ollama.base_url,
                api_key=settings.ollama.api_key,
            )
            health = await t.health()
            if health.ok:
                mode = "Cloud" if settings.ollama.api_key else "Local"
                return CheckResult(
                    "Provider ativo", True,
                    f"Ollama {mode} respondendo ({health.latency_ms}ms)",
                )
            return CheckResult(
                "Provider ativo", False, health.message or "Ollama não responde",
                hint="Verifique OLLAMA_BASE_URL e OLLAMA_API_KEY (se cloud)",
            )
        except Exception as exc:
            return CheckResult("Provider ativo", False, str(exc), hint="")

    elif provider == "anthropic":
        if not settings.anthropic.api_key:
            return CheckResult(
                "Provider ativo", False, "ANTHROPIC_API_KEY ausente",
                hint="Adicione ANTHROPIC_API_KEY no .env",
            )
        return CheckResult("Provider ativo", True, "Anthropic key configurada (sem teste ativo)")

    elif provider == "openai":
        if not settings.openai.api_key:
            return CheckResult(
                "Provider ativo", False, "OPENAI_API_KEY ausente",
                hint="Adicione OPENAI_API_KEY no .env",
            )
        return CheckResult("Provider ativo", True, "OpenAI key configurada (sem teste ativo)")

    return CheckResult("Provider ativo", True, f"{provider} configurado")


async def _check_migrations(settings) -> CheckResult:
    try:
        import asyncpg
        url = os.environ.get("POSTGRES_URL", "")
        if not url:
            return CheckResult("Migrações", False, "POSTGRES_URL não definido", hint="")

        conn = await asyncpg.connect(url, timeout=5)
        try:
            # Checa tabelas críticas das migrações 002-014
            critical = ["memories", "messages", "skill_invocations", "pending_approvals", "missions"]
            existing = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY($1)",
                critical,
            )
            found = {r["tablename"] for r in existing}
            missing = set(critical) - found

            if missing:
                return CheckResult(
                    "Migrações", False, f"tabelas faltando: {', '.join(missing)}",
                    hint="Aplique as migrações: `for f in core/migrations/*.sql; do psql -f $f; done`",
                )
            return CheckResult("Migrações", True, f"{len(found)}/{len(critical)} tabelas críticas presentes")
        finally:
            await conn.close()
    except Exception as exc:
        return CheckResult("Migrações", False, f"erro: {exc}", hint="")


def _check_docker() -> CheckResult:
    import shutil
    if shutil.which("docker"):
        return CheckResult("Docker", True, "instalado (opcional)")
    return CheckResult(
        "Docker", True, "não instalado [dim](opcional)[/dim]",
        hint="",
    )


def _check_workspace_paths(settings) -> CheckResult:
    paths = settings.agent.workspace_paths
    existing = [p for p in paths if Path(p).exists()]
    if existing:
        return CheckResult(
            "Workspace paths", True,
            f"{len(existing)}/{len(paths)} acessíveis: {', '.join(existing[:3])}",
        )
    return CheckResult(
        "Workspace paths", False, "nenhum path acessível",
        hint="Ajuste agent.workspace_paths em config/config.yaml",
    )
