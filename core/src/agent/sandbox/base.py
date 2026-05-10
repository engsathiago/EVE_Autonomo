from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class NetworkPolicy(Enum):
    DENY_ALL = "deny_all"
    ALLOWLIST = "allowlist"   # usa SandboxConfig.allowed_domains
    OPEN = "open"             # requer allow_open_network=True na SandboxPolicy


@dataclass
class SandboxConfig:
    image: str = "python:3.12-slim"
    cpu_limit: float = 1.0
    memory_limit_mb: int = 512
    wall_time_seconds: int = 30
    max_output_bytes: int = 1_000_000   # 1 MB stdout + stderr combinados
    fs_size_mb: int = 256
    network: NetworkPolicy = NetworkPolicy.DENY_ALL
    allowed_domains: list[str] = field(default_factory=list)
    workdir: str = "/work"
    read_only_root: bool = True


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    cpu_seconds: float
    memory_peak_mb: float
    timed_out: bool
    oom_killed: bool
    network_denied_attempts: list[str]
    files_out: dict[str, bytes] = field(default_factory=dict)


class Sandbox(ABC):
    """Interface comum para todos os backends de execução isolada."""

    @abstractmethod
    async def run(
        self,
        command: list[str] | str,
        *,
        stdin: bytes | None = None,
        files: dict[str, bytes] | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult: ...

    @abstractmethod
    async def cleanup(self) -> None: ...
