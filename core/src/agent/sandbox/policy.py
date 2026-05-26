from __future__ import annotations

from dataclasses import dataclass

from agent.sandbox.base import NetworkPolicy, SandboxConfig

_POLICY_REGISTRY: dict[str, SandboxPolicy] = {}


@dataclass
class SandboxPolicy:
    name: str
    config: SandboxConfig
    # Gate explícito: NetworkPolicy.OPEN só é aceito se este flag estiver True
    allow_open_network: bool = False
    # Se True, execução passa pelo Crítico (F7) antes de rodar
    require_critic_approval: bool = False


def _register(policy: SandboxPolicy) -> SandboxPolicy:
    _POLICY_REGISTRY[policy.name] = policy
    return policy


POLICY_DEFAULT = _register(
    SandboxPolicy(
        name="default",
        config=SandboxConfig(
            cpu_limit=1.0,
            memory_limit_mb=512,
            wall_time_seconds=30,
            network=NetworkPolicy.DENY_ALL,
        ),
    )
)

POLICY_SKILL_DEV = _register(
    SandboxPolicy(
        name="skill_dev",
        config=SandboxConfig(
            cpu_limit=2.0,
            memory_limit_mb=1024,
            wall_time_seconds=120,
            network=NetworkPolicy.ALLOWLIST,
            allowed_domains=[],  # preenchido pelo caller
        ),
    )
)

POLICY_UNTRUSTED = _register(
    SandboxPolicy(
        name="untrusted",
        config=SandboxConfig(
            cpu_limit=0.5,
            memory_limit_mb=256,
            wall_time_seconds=10,
            network=NetworkPolicy.DENY_ALL,
        ),
        require_critic_approval=True,
    )
)


POLICY_FINETUNE = _register(
    SandboxPolicy(
        name="finetune",
        config=SandboxConfig(
            cpu_limit=8.0,
            memory_limit_mb=32768,  # 32 GiB — merge+quantize pode precisar de RAM
            wall_time_seconds=7200,  # 2h — treino LoRA + merge em GPU
            network=NetworkPolicy.ALLOWLIST,
            allowed_domains=[
                "localhost",
                "127.0.0.1",
                "huggingface.co",  # download de tokenizers/configs de base models
            ],
        ),
        allow_open_network=False,  # somente domínios na allowlist
        require_critic_approval=False,  # treino não passa pelo Crítico
    )
)


def get_policy(name: str) -> SandboxPolicy:
    policy = _POLICY_REGISTRY.get(name)
    if policy is None:
        raise KeyError(
            f"Política de sandbox não encontrada: {name!r}. Disponíveis: {list(_POLICY_REGISTRY)}"
        )
    return policy
