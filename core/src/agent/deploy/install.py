"""
Install/uninstall do agente como serviço systemd (F10).

install():
  1. Cria usuário system 'agent' se não existe.
  2. Cria diretórios em /var/lib/agent/ e /etc/agent/.
  3. Renderiza e copia templates env.example e agent.service.
  4. Roda systemctl daemon-reload e enable.

uninstall():
  1. systemctl stop e disable.
  2. Remove unit file e diretórios de configuração.
  3. --keep-data preserva /var/lib/agent/.

Requer sudo (ou root) para criar usuários e escrever em /etc/.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from agent.observability.logger import get_logger

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SERVICE_NAME = "agent"

# Diretórios criados no install
_INSTALL_DIRS = [
    "/var/lib/agent/data",
    "/var/lib/agent/state",
    "/var/lib/agent/logs",
    "/var/lib/agent/backups",
    "/etc/agent",
]

_SYSTEMD_UNIT_DIR = "/etc/systemd/system"


def install(
    prefix: str = "/opt/agent",
    user: str = "agent",
    group: str = "agent",
    enable_systemd: bool = True,
) -> None:
    """Instala o agente como serviço no sistema."""
    prefix_path = Path(prefix)

    _check_root()
    _create_user(user, group)
    _create_dirs(user, group)

    # Copia .env.example para /etc/agent/.env se não existir
    env_dest = Path("/etc/agent/.env")
    if not env_dest.exists():
        env_src = _TEMPLATES_DIR / "env.example"
        shutil.copy(env_src, env_dest)
        env_dest.chmod(0o600)
        _chown(str(env_dest), user, group)
        log.info("install.env_copied", dest=str(env_dest))

    if enable_systemd:
        _install_systemd(prefix_path, user, group)

    log.info(
        "install.done",
        prefix=prefix,
        user=user,
        systemd=enable_systemd,
    )
    print(
        f"Instalado. Para iniciar: sudo systemctl start {_SERVICE_NAME}",
        file=sys.stderr,
    )


def uninstall(keep_data: bool = False) -> None:
    """Remove o serviço e arquivos de configuração."""
    _check_root()

    # Para e desabilita serviço
    for cmd in [
        ["systemctl", "stop", _SERVICE_NAME],
        ["systemctl", "disable", _SERVICE_NAME],
    ]:
        _run(cmd, check=False)

    unit_file = Path(_SYSTEMD_UNIT_DIR) / f"{_SERVICE_NAME}.service"
    unit_file.unlink(missing_ok=True)
    _run(["systemctl", "daemon-reload"], check=False)

    shutil.rmtree("/etc/agent", ignore_errors=True)

    if not keep_data:
        shutil.rmtree("/var/lib/agent", ignore_errors=True)
        log.info("uninstall.data_removed")

    log.info("uninstall.done", keep_data=keep_data)


def _install_systemd(prefix_path: Path, user: str, group: str) -> None:
    unit_src = _TEMPLATES_DIR / "agent.service"
    unit_content = unit_src.read_text()

    # Substituições de template
    venv_python = str(prefix_path / ".venv" / "bin" / "python")
    unit_content = (
        unit_content.replace("{{USER}}", user)
        .replace("{{GROUP}}", group)
        .replace("{{INSTALL_DIR}}", str(prefix_path))
        .replace("{{PYTHON}}", venv_python)
    )

    unit_dest = Path(_SYSTEMD_UNIT_DIR) / f"{_SERVICE_NAME}.service"
    unit_dest.write_text(unit_content)
    unit_dest.chmod(0o644)

    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", _SERVICE_NAME])
    log.info("install.systemd_enabled", unit=str(unit_dest))


def _create_dirs(user: str, group: str) -> None:
    for d in _INSTALL_DIRS:
        path = Path(d)
        path.mkdir(parents=True, exist_ok=True)
        _chown(d, user, group)
    log.info("install.dirs_created")


def _create_user(user: str, group: str) -> None:
    # Verifica se usuário já existe
    result = _run(["id", user], check=False)
    if result.returncode == 0:
        return

    if shutil.which("useradd"):
        _run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user])
    elif shutil.which("adduser"):
        _run(["adduser", "--system", "--no-create-home", "--shell", "/sbin/nologin", user])

    log.info("install.user_created", user=user)


def _chown(path: str, user: str, group: str) -> None:
    try:
        _run(["chown", "-R", f"{user}:{group}", path], check=False)
    except Exception:
        pass


def _check_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("install/uninstall requerem execução como root (sudo). Use: sudo agent deploy install")


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}\n{result.stderr}")
    return result
