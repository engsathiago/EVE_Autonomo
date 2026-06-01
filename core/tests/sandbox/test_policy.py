"""
Cobre §8 critérios 5, 8:
- Perfis pré-definidos com limites corretos.
- POLICY_UNTRUSTED.require_critic_approval=True.
- NetworkPolicy.OPEN sem allow_open_network=True bloqueado.
- get_policy com nome inválido lança KeyError.
"""
from __future__ import annotations

import pytest

from agent.sandbox.base import NetworkPolicy, SandboxConfig
from agent.sandbox.policy import (
    POLICY_DEFAULT,
    POLICY_SKILL_DEV,
    POLICY_UNTRUSTED,
    SandboxPolicy,
    get_policy,
)

# ---------------------------------------------------------------------------
# POLICY_DEFAULT
# ---------------------------------------------------------------------------

def test_policy_default_limits():
    p = POLICY_DEFAULT
    assert p.name == "default"
    assert p.config.cpu_limit == 1.0
    assert p.config.memory_limit_mb == 512
    assert p.config.wall_time_seconds == 30
    assert p.config.network == NetworkPolicy.DENY_ALL
    assert p.require_critic_approval is False
    assert p.allow_open_network is False


# ---------------------------------------------------------------------------
# POLICY_SKILL_DEV
# ---------------------------------------------------------------------------

def test_policy_skill_dev_uses_allowlist():
    p = POLICY_SKILL_DEV
    assert p.name == "skill_dev"
    assert p.config.network == NetworkPolicy.ALLOWLIST
    assert p.config.cpu_limit == 2.0
    assert p.config.memory_limit_mb == 1024
    assert p.config.wall_time_seconds == 120
    assert p.require_critic_approval is False


# ---------------------------------------------------------------------------
# POLICY_UNTRUSTED
# ---------------------------------------------------------------------------

def test_policy_untrusted_requires_critic():
    """POLICY_UNTRUSTED deve exigir aprovação do Crítico (§8 critério 5)."""
    p = POLICY_UNTRUSTED
    assert p.name == "untrusted"
    assert p.require_critic_approval is True
    assert p.config.network == NetworkPolicy.DENY_ALL
    assert p.config.memory_limit_mb == 256
    assert p.config.wall_time_seconds == 10
    assert p.config.cpu_limit == 0.5


# ---------------------------------------------------------------------------
# get_policy
# ---------------------------------------------------------------------------

def test_get_policy_default():
    p = get_policy("default")
    assert p is POLICY_DEFAULT


def test_get_policy_untrusted():
    p = get_policy("untrusted")
    assert p is POLICY_UNTRUSTED


def test_get_policy_nonexistent_raises():
    with pytest.raises(KeyError) as exc_info:
        get_policy("nonexistent_policy_xyz")
    assert "nonexistent_policy_xyz" in str(exc_info.value)


# ---------------------------------------------------------------------------
# NetworkPolicy.OPEN gate
# ---------------------------------------------------------------------------

async def test_open_network_requires_explicit_gate():
    """
    exec_tool com NetworkPolicy.OPEN sem allow_open_network=True deve levantar ValueError.
    Validação em exec_tool.py garante gate explícito (§4).
    """
    from agent.sandbox.policy import SandboxPolicy, _register
    from agent.tools.exec_tool import exec_tool
    from tests.sandbox.conftest import make_subprocess_sandbox

    # Registra política temporária com OPEN mas sem gate
    open_policy = SandboxPolicy(
        name="_test_open_no_gate",
        config=SandboxConfig(network=NetworkPolicy.OPEN),
        allow_open_network=False,  # gate fechado
    )
    _register(open_policy)

    try:
        with pytest.raises(ValueError, match="allow_open_network"):
            await exec_tool(
                "echo test",
                policy_name="_test_open_no_gate",
                make_sandbox=make_subprocess_sandbox,
            )
    finally:
        from agent.sandbox.policy import _POLICY_REGISTRY
        _POLICY_REGISTRY.pop("_test_open_no_gate", None)


def test_open_network_with_gate_allowed():
    """Com allow_open_network=True, a política OPEN é válida."""
    p = SandboxPolicy(
        name="test_open_allowed",
        config=SandboxConfig(network=NetworkPolicy.OPEN),
        allow_open_network=True,
    )
    assert p.allow_open_network is True
    assert p.config.network == NetworkPolicy.OPEN


# ---------------------------------------------------------------------------
# SandboxPolicy dataclass
# ---------------------------------------------------------------------------

def test_sandbox_policy_defaults():
    p = SandboxPolicy(name="test", config=SandboxConfig())
    assert p.allow_open_network is False
    assert p.require_critic_approval is False
