"""Subcomandos `agent web` — controle do Web UI (F11)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Gerencia o Web UI do agente.")
console = Console()

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_PID_FILE = Path(os.getenv("AGENT_WEB_PID_FILE", str(Path.home() / ".agent" / "web.pid")))
_TOKEN_FILE = Path(os.getenv("AGENT_WEB_TOKEN_FILE", str(Path.home() / ".agent" / "web_token")))


def _read_pid() -> int | None:
    try:
        return int(_PID_FILE.read_text().strip())
    except Exception:
        return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_token() -> str | None:
    try:
        return _TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


@app.command()
def start() -> None:
    """Sobe o Web UI (normalmente já sobe com o serviço da F10)."""
    console.print("[yellow]O Web UI sobe automaticamente com o serviço principal.[/yellow]")
    console.print(f"URL: http://{_DEFAULT_HOST}:{_DEFAULT_PORT}")
    tok = _read_token()
    if tok:
        console.print(f"Token: [green]{tok}[/green]")
    else:
        console.print("[yellow]Token não encontrado. Execute:[/yellow] agent web token-rotate")


@app.command()
def stop() -> None:
    """Para o serviço principal (que inclui o Web UI)."""
    pid = _read_pid()
    if pid and _is_running(pid):
        import signal
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sinal SIGTERM enviado para PID {pid}.[/green]")
    else:
        console.print("[yellow]Processo não encontrado. Use:[/yellow] agent deploy stop")


@app.command()
def status() -> None:
    """Mostra status do Web UI."""
    pid = _read_pid()
    if pid and _is_running(pid):
        console.print(f"[green]●[/green] Rodando (PID {pid}) em http://{_DEFAULT_HOST}:{_DEFAULT_PORT}")
    else:
        console.print("[red]●[/red] Parado")

    tok = _read_token()
    if tok:
        console.print(f"Token: [dim]{tok[:8]}…[/dim] ({len(tok)} chars)")
    else:
        console.print("[yellow]Token não configurado.[/yellow]")


@app.command("token-rotate")
def token_rotate() -> None:
    """Gera novo token e invalida o antigo (invalidação em <5s via cache TTL)."""
    try:
        from agent.web.auth import generate_token, write_token
        new_tok = generate_token()
        write_token(new_tok)
        console.print(f"[green]Novo token gerado e salvo em {_TOKEN_FILE}[/green]")
        console.print(f"Token: [bold green]{new_tok}[/bold green]")
        console.print("[dim]Sessões com token antigo expiram em até 5s.[/dim]")
    except ImportError:
        import secrets
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        new_tok = secrets.token_urlsafe(32)
        _TOKEN_FILE.write_text(new_tok + "\n", encoding="utf-8")
        _TOKEN_FILE.chmod(0o600)
        console.print(f"[green]Token gerado: {new_tok}[/green]")


@app.command("token-show")
def token_show() -> None:
    """Exibe o token atual (só em TTY interativo)."""
    if not sys.stdout.isatty():
        console.print("[red]Só exibe o token em TTY interativo.[/red]")
        raise typer.Exit(1)
    tok = _read_token()
    if tok:
        console.print(f"[bold green]{tok}[/bold green]")
    else:
        console.print("[yellow]Token não encontrado. Execute:[/yellow] agent web token-rotate")


@app.command()
def open() -> None:
    """Abre o Web UI no browser com o token na URL."""
    tok = _read_token()
    if not tok:
        console.print("[red]Token não encontrado. Execute:[/red] agent web token-rotate")
        raise typer.Exit(1)

    import urllib.parse
    url = f"http://{_DEFAULT_HOST}:{_DEFAULT_PORT}/?token={urllib.parse.quote(tok)}"
    console.print(f"Abrindo: {url}")

    # Tenta abrir no browser padrão (macOS/Linux/Windows)
    openers = ["open", "xdg-open", "start"]
    for opener in openers:
        try:
            subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            console.print("[green]Browser aberto.[/green]")
            return
        except FileNotFoundError:
            continue

    console.print(f"[yellow]Não foi possível abrir o browser. Acesse manualmente:[/yellow]\n{url}")
