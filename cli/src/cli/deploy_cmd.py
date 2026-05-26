"""
CLI deploy: agent deploy <subcomando>

Subcomandos:
  install    — instala como serviço systemd
  uninstall  — desinstala
  start      — systemctl start agent
  stop       — systemctl stop agent
  restart    — systemctl restart agent
  status     — systemd status + /health/ready + métricas-chave
  logs       — tail de logs JSON
  backup     — dispara backup manual via API
  restore    — restaura a partir de data YYYYMMDD
  doctor     — health/deep + checa permissões, paths, .env
  upgrade    — git pull + alembic upgrade + restart
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Gerencia o agente como serviço (deploy, health, backup).")
console = Console()

_DEFAULT_API = "http://127.0.0.1:8000"
_SERVICE = "agent"


def _api(path: str, method: str = "GET", json_body: dict | None = None) -> object:
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            if method == "POST":
                return client.post(f"{_DEFAULT_API}{path}", json=json_body or {})
            return client.get(f"{_DEFAULT_API}{path}")
    except Exception as exc:
        console.print(f"[red]API inacessível: {exc}[/red]")
        raise typer.Exit(1) from exc


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["systemctl", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode not in (0, 1):
        console.print(result.stderr, style="red")
        raise typer.Exit(result.returncode)
    return result


# ── install ───────────────────────────────────────────────────────────────────


@app.command()
def install(
    prefix: str = typer.Option("/opt/agent", help="Diretório de instalação"),
    user: str = typer.Option("agent", help="Usuário do sistema"),
    systemd: bool = typer.Option(True, "--systemd/--no-systemd", help="Instala unit file"),
) -> None:
    """Instala o agente como serviço. Requer sudo."""
    from agent.deploy.install import install as _install

    try:
        _install(prefix=prefix, user=user, enable_systemd=systemd)
        console.print("[green]Instalação concluída.[/green]")
    except PermissionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command()
def uninstall(
    keep_data: bool = typer.Option(False, "--keep-data", help="Preserva /var/lib/agent/"),
) -> None:
    """Remove o serviço. Requer sudo."""
    from agent.deploy.install import uninstall as _uninstall

    if not typer.confirm(f"Desinstalar serviço '{_SERVICE}'?"):
        raise typer.Exit()
    try:
        _uninstall(keep_data=keep_data)
        console.print("[green]Remoção concluída.[/green]")
    except PermissionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


# ── systemctl wrappers ────────────────────────────────────────────────────────


@app.command()
def start() -> None:
    """Inicia o serviço via systemctl."""
    _systemctl("start", _SERVICE)
    console.print(f"[green]Serviço {_SERVICE} iniciado.[/green]")


@app.command()
def stop() -> None:
    """Para o serviço via systemctl."""
    _systemctl("stop", _SERVICE)
    console.print(f"[yellow]Serviço {_SERVICE} parado.[/yellow]")


@app.command()
def restart() -> None:
    """Reinicia o serviço via systemctl."""
    _systemctl("restart", _SERVICE)
    console.print(f"[green]Serviço {_SERVICE} reiniciado.[/green]")


@app.command()
def status() -> None:
    """Exibe status systemd + health/ready + métricas-chave."""
    result = _systemctl("status", _SERVICE, check=False)
    console.print(result.stdout or result.stderr)

    try:
        resp = _api("/health/ready")
        data = resp.json()  # type: ignore[union-attr]
        style = "green" if resp.status_code == 200 else "red"  # type: ignore[union-attr]
        console.print(f"\n[{style}]Health ready: {resp.status_code}[/{style}]")  # type: ignore[union-attr]
        console.print_json(json.dumps(data))
    except Exception as exc:
        console.print(f"[red]Health inacessível: {exc}[/red]")

    try:
        metrics_text = _api("/metrics").text  # type: ignore[union-attr]
        for line in metrics_text.splitlines():
            if line.startswith(("agent_uptime_seconds", "agent_missions_total")):
                console.print(f"[dim]{line}[/dim]")
    except Exception:
        pass


@app.command()
def logs(
    follow: bool = typer.Option(False, "-f", "--follow", help="Segue o log em tempo real"),
    since: str | None = typer.Option(None, help="Ex: 1h, 24h, 7d"),
    worker: str | None = typer.Option(None, help="Filtra por worker"),
) -> None:
    """Exibe logs JSON do agente."""
    log_file = Path("/var/lib/agent/logs/agent.log")

    if not log_file.exists():
        cmd = ["journalctl", "-u", _SERVICE, "--no-pager"]
        if follow:
            cmd.append("-f")
        if since:
            cmd += ["--since", f"-{since}"]
        subprocess.run(cmd)
        return

    cutoff: datetime | None = None
    if since:
        qty = int(since[:-1])
        unit = since[-1]
        delta = {"h": timedelta(hours=qty), "d": timedelta(days=qty)}.get(unit)
        if delta:
            cutoff = datetime.utcnow() - delta

    def _emit(line: str) -> None:
        if not line.strip():
            return
        try:
            entry = json.loads(line)
            if worker and entry.get("worker") != worker:
                return
            if cutoff:
                ts_str = entry.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        return
                except ValueError:
                    pass
            console.print(line.rstrip())
        except json.JSONDecodeError:
            console.print(line.rstrip())

    if follow:
        import time

        with open(log_file) as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    _emit(line)
                else:
                    time.sleep(0.2)
    else:
        with open(log_file) as f:
            for line in f:
                _emit(line)


@app.command()
def backup() -> None:
    """Dispara backup manual via API."""
    resp = _api("/api/v1/deploy/backup", method="POST")
    console.print_json(json.dumps(resp.json()))  # type: ignore[union-attr]


@app.command()
def restore(
    date: str = typer.Option(..., help="Data no formato YYYYMMDD"),
) -> None:
    """Restaura backups de uma data específica."""
    if not typer.confirm(f"Restaurar backup de {date}? Substitui o banco atual."):
        raise typer.Exit()
    resp = _api("/api/v1/deploy/restore", method="POST", json_body={"date": date})
    console.print_json(json.dumps(resp.json()))  # type: ignore[union-attr]


@app.command()
def doctor() -> None:
    """Diagnóstico completo: health/deep + paths + .env."""
    issues: list[str] = []

    try:
        resp = _api("/health/deep")
        icon = "✓" if resp.status_code == 200 else "✗"  # type: ignore[union-attr]
        style = "green" if resp.status_code == 200 else "red"  # type: ignore[union-attr]
        console.print(f"[{style}]{icon} health/deep: {resp.status_code}[/{style}]")  # type: ignore[union-attr]
        console.print_json(json.dumps(resp.json()))  # type: ignore[union-attr]
    except Exception as exc:
        issues.append(f"health/deep inacessível: {exc}")

    for path in ["/var/lib/agent", "/etc/agent", "/etc/agent/.env"]:
        exists = Path(path).exists()
        icon = "✓" if exists else "✗"
        style = "green" if exists else "red"
        console.print(f"[{style}]{icon} {path}[/{style}]")
        if not exists:
            issues.append(f"path ausente: {path}")

    env_file = Path("/etc/agent/.env")
    if env_file.exists() and "CHANGE_ME" in env_file.read_text():
        issues.append(".env contém CHANGE_ME — preencha antes de produção")

    if issues:
        console.print("\n[red]Problemas:[/red]")
        for issue in issues:
            console.print(f"  [red]✗ {issue}[/red]")
        raise typer.Exit(1)
    else:
        console.print("\n[green]Tudo OK.[/green]")


@app.command()
def upgrade(
    to: str | None = typer.Option(None, help="Branch/tag de destino"),
) -> None:
    """Pull de código + migrations + restart."""
    console.print("Parando serviço...")
    _systemctl("stop", _SERVICE, check=False)

    if to:
        subprocess.run(["git", "fetch", "origin"], check=True)
        subprocess.run(["git", "checkout", to], check=True)
    subprocess.run(["git", "pull"], check=True)

    console.print("Aplicando migrations...")
    subprocess.run(
        ["python", "-m", "alembic", "upgrade", "head"],
        cwd="/opt/agent",
        check=True,
    )

    console.print("Reiniciando...")
    _systemctl("start", _SERVICE)
    console.print("[green]Upgrade concluído.[/green]")
