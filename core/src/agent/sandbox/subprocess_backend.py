"""
SubprocessSandbox: backend de fallback quando Docker não está disponível.

Limitações de segurança (documentadas — não são bugs):
- ISOLAMENTO DE REDE NÃO É GARANTIDO. A definição de http_proxy atrapalha a
  maioria dos clientes HTTP mas não é um controle de segurança real. Se você
  precisa de isolamento de rede confiável, use DockerSandbox.
- ISOLAMENTO DE FILESYSTEM É PARCIAL. O processo roda em um tempdir efêmero
  mas pode acessar o resto do filesystem do host se tiver permissão suficiente.
- RLIMIT_AS não está disponível no macOS (silenciosamente ignorado).

Adequado para: desenvolvimento local, CI sem Docker-in-Docker, testes.
NÃO adequado para: execução de código não confiável em produção.
"""

from __future__ import annotations

import asyncio
import os
import resource
import shlex
import tempfile
import time
from pathlib import Path

from agent.observability.logger import get_logger
from agent.sandbox.base import NetworkPolicy, Sandbox, SandboxConfig, SandboxResult
from agent.sandbox.exceptions import SandboxBackendUnsupported

log = get_logger(__name__)

_BYTES_PER_MB = 1024 * 1024


def _apply_rlimits(config: SandboxConfig) -> None:
    """Chamado como preexec_fn: aplica limites de recurso no processo filho."""
    try:
        mem_bytes = config.memory_limit_mb * _BYTES_PER_MB
        # RLIMIT_AS: tamanho máximo do espaço de endereços virtual (Linux only)
        if hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (OSError, ValueError):
        pass

    try:
        # RLIMIT_CPU: segundos de CPU (arredondado pra cima do wall_time)
        cpu_s = max(1, config.wall_time_seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
    except (OSError, ValueError):
        pass

    try:
        fs_bytes = config.fs_size_mb * _BYTES_PER_MB
        resource.setrlimit(resource.RLIMIT_FSIZE, (fs_bytes, fs_bytes))
    except (OSError, ValueError):
        pass

    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    except (OSError, ValueError):
        pass


class SubprocessSandbox(Sandbox):
    """
    Execução isolada via subprocess com rlimits e tempdir efêmero.

    backend=subprocess insecure=true — ver docstring do módulo para limitações.
    """

    def __init__(self, config: SandboxConfig) -> None:
        if config.network not in (NetworkPolicy.DENY_ALL,):
            raise SandboxBackendUnsupported(
                "SubprocessSandbox só suporta NetworkPolicy.DENY_ALL. "
                "Para ALLOWLIST ou OPEN use DockerSandbox."
            )
        self._config = config
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

    async def run(
        self,
        command: list[str] | str,
        *,
        stdin: bytes | None = None,
        files: dict[str, bytes] | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        log.info("sandbox.subprocess.start", backend="subprocess", insecure=True)

        self._tmpdir = tempfile.TemporaryDirectory()
        workdir = Path(self._tmpdir.name)

        # Escreve arquivos de input no tmpdir
        if files:
            for name, data in files.items():
                dest = workdir / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)

        # Env mínimo + proxy best-effort para bloquear HTTP
        proc_env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "HOME": str(workdir),
            # Best-effort: aponta proxies para porta que não existe
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        }
        if env:
            proc_env.update(env)

        cmd: list[str] = shlex.split(command) if isinstance(command, str) else command

        t0 = time.monotonic()
        timed_out = False
        stdout_bytes = b""
        stderr_bytes = b""

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(workdir),
                env=proc_env,
                preexec_fn=lambda: _apply_rlimits(self._config),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=stdin),
                    timeout=self._config.wall_time_seconds,
                )
            except TimeoutError:
                timed_out = True
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

        except Exception as exc:
            log.warning("sandbox.subprocess.launch_failed", error=str(exc))
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

        half = self._config.max_output_bytes // 2
        stdout_str = stdout_bytes[:half].decode("utf-8", errors="replace")
        stderr_str = stderr_bytes[:half].decode("utf-8", errors="replace")

        exit_code = proc.returncode if not timed_out else -1

        log.info(
            "sandbox.subprocess.done",
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

        return SandboxResult(
            exit_code=exit_code if exit_code is not None else -1,
            stdout=stdout_str,
            stderr=stderr_str,
            duration_ms=duration_ms,
            cpu_seconds=duration_ms / 1000.0,  # aproximação — rlimit real não retorna uso
            memory_peak_mb=0.0,
            timed_out=timed_out,
            oom_killed=False,  # rlimit OOM no subprocess não é detectável de forma confiável
            network_denied_attempts=[],
        )

    async def cleanup(self) -> None:
        if self._tmpdir is not None:
            try:
                self._tmpdir.cleanup()
            except Exception:
                pass
            self._tmpdir = None
