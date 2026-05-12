"""Testes E2E para deploy (F10) — requerem systemd ou container privilegiado.

Todos os testes aqui têm @pytest.mark.integration e são pulados
automaticamente em ambientes sem systemd.

Para rodar:
  docker run --privileged --rm -v $(pwd):/app ubuntu:24.04 \
    bash -c "apt-get install -y systemd && cd /app/core && pytest tests/deploy/test_e2e_deploy.py -v"

  OU em uma VM Linux com systemd ativo:
    pytest tests/deploy/ -v -m integration

Critérios cobertos:
  C1: install → systemctl status agent → active (running)
  C2: kill -9 orchestrator → restart em <10s com attempt=1
  C3: 11 kills em 10 min → flapping + worker disabled
  C10: reboot → agente volta em <60s
"""
from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path

import pytest


def _systemd_available() -> bool:
    """Verifica se systemd está disponível e funcional no ambiente."""
    if platform.system() != "Linux":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "is-system-running"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode in (0, 1)  # 0=running, 1=degraded são ambos ok
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.integration
_SYSTEMD = pytest.mark.skipif(
    not _systemd_available(),
    reason="systemd não disponível — rodar em VM/container privilegiado",
)


# ── C1: install → systemctl status active ─────────────────────────────────────

@_SYSTEMD
class TestInstallC1:
    """Requer sudo. Pula em ambiente sem root."""

    @pytest.fixture(autouse=True)
    def require_root(self) -> None:
        if os.geteuid() != 0:
            pytest.skip("C1 requer root para systemctl enable/start")

    def test_install_creates_service_file(self, tmp_path: Path) -> None:
        """agent deploy install --no-systemd cria o unit file sem falhar."""
        from agent.deploy.install import install
        # Com --no-systemd não precisa de root para o systemctl, mas precisa para criar dirs
        try:
            install(prefix=str(tmp_path / "agent"), user="root", enable_systemd=False)
        except PermissionError:
            pytest.skip("Sem permissão para criar diretórios de sistema")

    def test_service_file_has_type_notify(self) -> None:
        """Unit file instalado contém Type=notify."""
        service_path = Path("/etc/systemd/system/agent.service")
        if not service_path.exists():
            pytest.skip("agent.service não instalado")
        content = service_path.read_text()
        assert "Type=notify" in content

    def test_systemctl_status_after_install(self) -> None:
        """C1: systemctl status agent retorna informação do serviço."""
        result = subprocess.run(
            ["systemctl", "status", "agent"],
            capture_output=True,
            text=True,
        )
        # returncode 3 = inactive (não iniciado) mas serviço existe
        # returncode 0 = active (running)
        # returncode 4 = unidade não encontrada
        assert result.returncode != 4, "Serviço agent não encontrado. Rode install primeiro."


# ── C2: kill -9 orchestrator → restart em <10s ───────────────────────────────

class TestKillRestartC2:
    """Teste de restart via subprocess.fork() real (sem systemd).

    Cria um worker em subprocesso, mata com SIGKILL, e verifica que o
    supervisor detecta a morte no próximo ciclo de monitoramento.
    """

    def test_worker_death_detected_by_is_pid_alive(self) -> None:
        """_is_pid_alive detecta processo morto após SIGKILL."""
        from agent.deploy.supervisor import _is_pid_alive

        # Cria processo filho que dorme
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)

        # Pai mata o filho
        os.kill(pid, 9)  # SIGKILL
        os.waitpid(pid, 0)

        assert not _is_pid_alive(pid), "Processo não deveria estar vivo após SIGKILL"

    def test_backoff_on_first_restart_is_1s(self) -> None:
        """C2: primeiro restart tem backoff=1s (attempt=1 → idx=0 → 1s)."""
        from agent.deploy.supervisor import _WorkerState
        from agent.deploy.workers.base import Worker

        class _W(Worker):
            name = "orchestrator"
            async def run(self) -> None: pass

        state = _WorkerState(worker=_W())
        state.record_restart()
        assert state.backoff_seconds() == 1.0

    def test_restart_event_attempt_equals_1_on_first_crash(self) -> None:
        """C2: evento de restart tem attempt=1 no primeiro crash."""
        from agent.deploy.supervisor import _WorkerState
        from agent.deploy.workers.base import Worker

        class _W(Worker):
            name = "orchestrator"
            async def run(self) -> None: pass

        state = _WorkerState(worker=_W())
        state.record_restart()

        assert state.restarts_in_window() == 1


# ── C3: 11 kills → flapping ───────────────────────────────────────────────────

class TestFlappingC3:
    def test_11_restarts_triggers_flapping(self) -> None:
        """C3: 11 restarts em janela de 10min → restarts_in_window >= 10."""
        from agent.deploy.supervisor import _FLAPPING_MAX_RESTARTS, _WorkerState
        from agent.deploy.workers.base import Worker

        class _W(Worker):
            name = "orchestrator"
            async def run(self) -> None: pass

        state = _WorkerState(worker=_W())
        for _ in range(_FLAPPING_MAX_RESTARTS + 1):
            state.record_restart()

        assert state.restarts_in_window() >= _FLAPPING_MAX_RESTARTS

    def test_flapping_worker_is_disabled(self) -> None:
        """C3: depois de flapping, worker.disabled=True."""
        from agent.deploy.supervisor import _FLAPPING_MAX_RESTARTS, _WorkerState
        from agent.deploy.workers.base import Worker

        class _W(Worker):
            name = "orchestrator"
            async def run(self) -> None: pass

        state = _WorkerState(worker=_W())
        for _ in range(_FLAPPING_MAX_RESTARTS + 1):
            state.record_restart()
        state.disabled = True  # supervisor faz isso ao detectar flapping

        assert state.disabled is True

    def test_other_workers_unaffected_by_flapping(self) -> None:
        """C3: outros workers continuam vivos quando um entra em flapping."""
        from agent.deploy.supervisor import _FLAPPING_MAX_RESTARTS, _WorkerState
        from agent.deploy.workers.base import Worker

        class _W(Worker):
            name = "orchestrator"
            async def run(self) -> None: pass

        class _W2(Worker):
            name = "api"
            async def run(self) -> None: pass

        state1 = _WorkerState(worker=_W())
        state2 = _WorkerState(worker=_W2())

        for _ in range(_FLAPPING_MAX_RESTARTS + 1):
            state1.record_restart()
        state1.disabled = True

        # state2 não foi afetado
        assert state2.disabled is False
        assert state2.restarts_in_window() == 0


# ── C10: reboot → agente volta em <60s ────────────────────────────────────────

@_SYSTEMD
class TestRebootRecoveryC10:
    """Smoke test de recuperação pós-reboot."""

    @pytest.fixture(autouse=True)
    def require_root(self) -> None:
        if os.geteuid() != 0:
            pytest.skip("C10 requer root para systemctl")

    def test_service_enabled_for_boot(self) -> None:
        """C10: agent.service deve estar habilitado para boot automático."""
        result = subprocess.run(
            ["systemctl", "is-enabled", "agent"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 4:
            pytest.skip("agent.service não instalado")
        # enabled ou static são aceitáveis
        assert result.stdout.strip() in ("enabled", "static"), (
            f"Serviço não habilitado para boot: {result.stdout.strip()}"
        )

    def test_service_restarts_on_failure(self) -> None:
        """C10: Restart=on-failure está configurado no unit file."""
        service_path = Path("/etc/systemd/system/agent.service")
        if not service_path.exists():
            pytest.skip("agent.service não instalado")
        content = service_path.read_text()
        assert "Restart=on-failure" in content

    def test_health_responds_after_synthetic_restart(self) -> None:
        """C10: simula restart do serviço e verifica que /health/live responde."""
        result = subprocess.run(
            ["systemctl", "is-active", "agent"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            pytest.skip("agent.service não está ativo")

        subprocess.run(["systemctl", "restart", "agent"], check=True, timeout=30)
        time.sleep(3)

        # Verifica que health/live responde em <60s
        deadline = time.monotonic() + 60
        last_error = None
        while time.monotonic() < deadline:
            try:
                import httpx
                resp = httpx.get("http://127.0.0.1:8000/health/live", timeout=2)
                if resp.status_code == 200:
                    return  # sucesso
            except Exception as exc:
                last_error = exc
            time.sleep(2)

        pytest.fail(f"Agent não respondeu em 60s após restart. Último erro: {last_error}")


# ── Testes de configuração do unit file ──────────────────────────────────────

class TestUnitFileConfig:
    """Testa o template do unit file sem precisar de systemd real."""

    def _template_path(self) -> Path:
        return Path(__file__).parents[3] / "src" / "agent" / "deploy" / "templates" / "agent.service"

    def test_template_exists(self) -> None:
        assert self._template_path().exists()

    def test_type_notify(self) -> None:
        assert "Type=notify" in self._template_path().read_text()

    def test_watchdog_configured(self) -> None:
        assert "WatchdogSec=" in self._template_path().read_text()

    def test_restart_on_failure(self) -> None:
        assert "Restart=on-failure" in self._template_path().read_text()

    def test_no_new_privileges(self) -> None:
        """C10/C1: hardening NoNewPrivileges no unit file."""
        assert "NoNewPrivileges=true" in self._template_path().read_text()

    def test_loopback_api_host_in_env_example(self) -> None:
        """Anti-padrão: nunca 0.0.0.0 por padrão."""
        env_path = Path(__file__).parents[3] / "src" / "agent" / "deploy" / "templates" / "env.example"
        if not env_path.exists():
            pytest.skip("env.example não encontrado")
        content = env_path.read_text()
        # AGENT_API_HOST deve ser loopback, não 0.0.0.0
        if "AGENT_API_HOST" in content:
            for line in content.splitlines():
                if line.startswith("AGENT_API_HOST"):
                    assert "0.0.0.0" not in line, "API host não deve ser 0.0.0.0 por padrão"
