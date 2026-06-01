"""
Cobre §8 critério 1: Sandbox ABC e backends implementados.
Testa dataclasses, defaults, exceptions e factory de backend.
"""
from __future__ import annotations

from agent.sandbox.base import NetworkPolicy, Sandbox, SandboxConfig, SandboxResult
from agent.sandbox.exceptions import (
    SandboxBackendUnsupported,
    SandboxCriticRejected,
    SandboxNetworkDenied,
    SandboxOOM,
    SandboxTimeout,
)

# ---------------------------------------------------------------------------
# SandboxConfig defaults
# ---------------------------------------------------------------------------

def test_sandbox_config_defaults():
    cfg = SandboxConfig()
    assert cfg.image == "python:3.12-slim"
    assert cfg.cpu_limit == 1.0
    assert cfg.memory_limit_mb == 512
    assert cfg.wall_time_seconds == 30
    assert cfg.max_output_bytes == 1_000_000
    assert cfg.fs_size_mb == 256
    assert cfg.network == NetworkPolicy.DENY_ALL
    assert cfg.allowed_domains == []
    assert cfg.workdir == "/work"
    assert cfg.read_only_root is True


def test_sandbox_config_custom():
    cfg = SandboxConfig(
        cpu_limit=2.0,
        memory_limit_mb=1024,
        wall_time_seconds=60,
        network=NetworkPolicy.ALLOWLIST,
        allowed_domains=["pypi.org"],
    )
    assert cfg.cpu_limit == 2.0
    assert cfg.memory_limit_mb == 1024
    assert cfg.wall_time_seconds == 60
    assert cfg.network == NetworkPolicy.ALLOWLIST
    assert cfg.allowed_domains == ["pypi.org"]


# ---------------------------------------------------------------------------
# SandboxResult defaults
# ---------------------------------------------------------------------------

def test_sandbox_result_fields():
    r = SandboxResult(
        exit_code=0,
        stdout="ok\n",
        stderr="",
        duration_ms=100,
        cpu_seconds=0.1,
        memory_peak_mb=10.0,
        timed_out=False,
        oom_killed=False,
        network_denied_attempts=[],
    )
    assert r.exit_code == 0
    assert r.files_out == {}   # default vazio


def test_sandbox_result_files_out():
    r = SandboxResult(
        exit_code=0,
        stdout="",
        stderr="",
        duration_ms=10,
        cpu_seconds=0.01,
        memory_peak_mb=0.0,
        timed_out=False,
        oom_killed=False,
        network_denied_attempts=[],
        files_out={"out.txt": b"content"},
    )
    assert r.files_out == {"out.txt": b"content"}


# ---------------------------------------------------------------------------
# NetworkPolicy enum
# ---------------------------------------------------------------------------

def test_network_policy_values():
    assert NetworkPolicy.DENY_ALL.value == "deny_all"
    assert NetworkPolicy.ALLOWLIST.value == "allowlist"
    assert NetworkPolicy.OPEN.value == "open"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

def test_sandbox_timeout_message():
    exc = SandboxTimeout(30)
    assert "30" in str(exc)
    assert exc.wall_time_s == 30


def test_sandbox_oom_message():
    exc = SandboxOOM(256)
    assert "256" in str(exc)
    assert exc.limit_mb == 256


def test_sandbox_network_denied():
    exc = SandboxNetworkDenied("evil.com")
    assert "evil.com" in str(exc)
    assert exc.domain == "evil.com"


def test_sandbox_backend_unsupported():
    exc = SandboxBackendUnsupported("docker not found")
    assert "docker not found" in str(exc)
    assert exc.reason == "docker not found"


def test_sandbox_critic_rejected():
    exc = SandboxCriticRejected("risco alto")
    assert "risco alto" in str(exc)
    assert exc.reasoning == "risco alto"


# ---------------------------------------------------------------------------
# Factory de backend (get_default_backend / make_sandbox)
# ---------------------------------------------------------------------------

def test_get_default_backend_returns_class():
    from agent.sandbox.docker_backend import get_default_backend
    backend_cls = get_default_backend()
    assert issubclass(backend_cls, Sandbox)


def test_sandbox_backend_env_override_subprocess(monkeypatch):
    monkeypatch.setenv("AGENT_SANDBOX_BACKEND", "subprocess")
    # Importação fresca
    import importlib

    from agent.sandbox import docker_backend as db
    importlib.reload(db)
    from agent.sandbox.subprocess_backend import SubprocessSandbox
    cls = db.get_default_backend()
    assert cls is SubprocessSandbox


def test_sandbox_backend_env_override_docker(monkeypatch):
    monkeypatch.setenv("AGENT_SANDBOX_BACKEND", "docker")
    import importlib

    from agent.sandbox import docker_backend as db
    importlib.reload(db)
    from agent.sandbox.docker_backend import DockerSandbox
    cls = db.get_default_backend()
    assert cls is DockerSandbox


def test_make_sandbox_returns_sandbox_instance():
    from agent.sandbox.docker_backend import make_sandbox
    cfg = SandboxConfig()
    sandbox = make_sandbox(cfg)
    assert isinstance(sandbox, Sandbox)
