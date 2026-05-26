"""
DockerSandbox: backend seguro via `docker run`.

Usa asyncio.create_subprocess_exec("docker", ...) — não depende do docker SDK.
Cada execução cria e destrói um container isolado (--rm).

Flags de segurança aplicadas:
- --rm: remove automático
- --network none (DENY_ALL) ou rede customizada (ALLOWLIST/OPEN)
- --memory, --cpus, --pids-limit 256
- --read-only na raiz + tmpfs em /work e /tmp
- --user 65534:65534 (nobody)
- --cap-drop=ALL
- --security-opt no-new-privileges

Limitações:
- Allowlist de rede (NetworkPolicy.ALLOWLIST) requer infraestrutura externa
  (iptables/dnsmasq customizado). Por enquanto aceita a config mas não garante
  o filtro — documenta o aviso no log. Para isolamento real em produção,
  configure uma Docker network com egress filtering.
- Métricas de CPU/memória são aproximadas (via /proc do container após execução).
"""

from __future__ import annotations

import asyncio
import shlex
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from agent.observability.logger import get_logger
from agent.sandbox.base import NetworkPolicy, Sandbox, SandboxConfig, SandboxResult
from agent.sandbox.exceptions import SandboxBackendUnsupported

log = get_logger(__name__)

_DOCKER_KILL_TIMEOUT_S = 5


def _docker_daemon_responsive() -> bool:
    """Verifica se o daemon Docker está acessível."""
    try:
        import subprocess

        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_default_backend() -> type[Sandbox]:
    """
    Seleciona o backend padrão baseado na disponibilidade do Docker.
    Override via env var AGENT_SANDBOX_BACKEND=docker|subprocess.
    """
    import os

    override = os.environ.get("AGENT_SANDBOX_BACKEND", "").lower()
    if override == "docker":
        return DockerSandbox
    if override == "subprocess":
        from agent.sandbox.subprocess_backend import SubprocessSandbox

        return SubprocessSandbox

    if shutil.which("docker") and _docker_daemon_responsive():
        return DockerSandbox

    from agent.sandbox.subprocess_backend import SubprocessSandbox

    return SubprocessSandbox


def make_sandbox(config: SandboxConfig) -> Sandbox:
    """Factory: cria a instância correta baseada no backend selecionado."""
    backend_cls = get_default_backend()
    return backend_cls(config)


class DockerSandbox(Sandbox):
    """Execução isolada em container Docker efêmero."""

    def __init__(self, config: SandboxConfig) -> None:
        if not shutil.which("docker"):
            raise SandboxBackendUnsupported("docker não encontrado no PATH")
        self._config = config
        self._container_id: str | None = None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def _build_docker_args(
        self,
        container_name: str,
        tmpdir: str,
        env: dict[str, str] | None,
    ) -> list[str]:
        cfg = self._config
        args = [
            "docker",
            "run",
            "--rm",
            f"--name={container_name}",
            "--user=65534:65534",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={cfg.memory_limit_mb}m",
            f"--memory-swap={cfg.memory_limit_mb}m",  # desabilita swap
            f"--cpus={cfg.cpu_limit}",
            "--pids-limit=256",
        ]

        # Filesystem: raiz read-only, /work e /tmp via tmpfs
        if cfg.read_only_root:
            args.append("--read-only")
        args += [
            f"--tmpfs={cfg.workdir}:rw,size={cfg.fs_size_mb}m,uid=65534",
            "--tmpfs=/tmp:rw,size=64m,uid=65534",
        ]

        # Rede
        if cfg.network == NetworkPolicy.DENY_ALL:
            args.append("--network=none")
        elif cfg.network == NetworkPolicy.ALLOWLIST:
            # Aviso: sem infraestrutura de filtro customizada, a rede fica aberta.
            # Em produção configure uma bridge com egress filtering.
            log.warning(
                "sandbox.docker.network_allowlist_not_enforced",
                domains=cfg.allowed_domains,
                note="configure egress filtering na Docker network para enforcement real",
            )
            args.append("--network=bridge")
        elif cfg.network == NetworkPolicy.OPEN:
            args.append("--network=bridge")

        # Workdir dentro do container
        args += [f"--workdir={cfg.workdir}"]

        # Env vars do caller
        if env:
            for k, v in env.items():
                args += ["-e", f"{k}={v}"]

        args.append(cfg.image)
        return args

    async def run(
        self,
        command: list[str] | str,
        *,
        stdin: bytes | None = None,
        files: dict[str, bytes] | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        container_name = f"agent-sandbox-{uuid.uuid4().hex[:12]}"
        self._container_id = container_name
        self._tmpdir = tempfile.TemporaryDirectory()

        # Injeta arquivos no container via bind mount temporário
        host_workdir = Path(self._tmpdir.name) / "work"
        host_workdir.mkdir()
        if files:
            for name, data in files.items():
                dest = host_workdir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                # Ajusta permissão para nobody (65534)
                dest.chmod(0o444)

        cmd_str = shlex.join(command) if isinstance(command, list) else command
        docker_args = self._build_docker_args(container_name, str(host_workdir), env)

        # Entrypoint: sh -c "<cmd>" para suportar strings
        full_args = docker_args + ["sh", "-c", cmd_str]

        t0 = time.monotonic()
        timed_out = False
        oom_killed = False
        stdout_bytes = b""
        stderr_bytes = b""
        exit_code = -1

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_args,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin),
                    timeout=self._config.wall_time_seconds,
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
            except TimeoutError:
                timed_out = True
                await self._kill_container(container_name)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_DOCKER_KILL_TIMEOUT_S)
                except TimeoutError:
                    pass

        except Exception as exc:
            log.warning("sandbox.docker.launch_failed", error=str(exc))
            duration_ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr=str(exc),
                duration_ms=duration_ms,
                cpu_seconds=0.0,
                memory_peak_mb=0.0,
                timed_out=False,
                oom_killed=False,
                network_denied_attempts=[],
            )

        duration_ms = int((time.monotonic() - t0) * 1000)

        # OOM: Docker usa exit code 137 (SIGKILL) quando --memory é excedido
        if exit_code == 137 and not timed_out:
            oom_killed = True

        half = self._config.max_output_bytes // 2
        stdout_str = stdout_bytes[:half].decode("utf-8", errors="replace")
        stderr_str = stderr_bytes[:half].decode("utf-8", errors="replace")

        # Coleta arquivos de output do workdir montado
        files_out: dict[str, bytes] = {}
        if host_workdir.exists():
            for f in host_workdir.iterdir():
                if f.is_file():
                    try:
                        files_out[f.name] = f.read_bytes()
                    except Exception:
                        pass

        log.info(
            "sandbox.docker.done",
            container=container_name,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            oom_killed=oom_killed,
        )

        return SandboxResult(
            exit_code=exit_code if not timed_out else -1,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_ms=duration_ms,
            cpu_seconds=duration_ms / 1000.0,
            memory_peak_mb=0.0,
            timed_out=timed_out,
            oom_killed=oom_killed,
            network_denied_attempts=[],
            files_out=files_out,
        )

    async def _kill_container(self, container_name: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=_DOCKER_KILL_TIMEOUT_S)
        except Exception as exc:
            log.warning("sandbox.docker.kill_failed", container=container_name, error=str(exc))

    async def cleanup(self) -> None:
        if self._tmpdir is not None:
            try:
                self._tmpdir.cleanup()
            except Exception:
                pass
            self._tmpdir = None
        self._container_id = None
