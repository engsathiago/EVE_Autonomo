"""
exec_tool: único ponto de execução de comandos arbitrários no agente.

Toda execução passa pela sandbox. Se a política exige aprovação do Crítico,
a execução é bloqueada até aprovação ou rejeitada com exit_code=-1.

Injeção de dependência:
- `make_sandbox` vem de docker_backend por padrão (auto-seleção de backend).
- `critic` é opcional; sem ele, require_critic_approval é ignorado.
- `registry` é opcional; sem ele, não persiste no banco.

Para testes: passe make_sandbox=lambda cfg: FakeSandbox(cfg).
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from agent.observability.logger import get_logger
from agent.sandbox.base import Sandbox, SandboxConfig, SandboxResult
from agent.sandbox.docker_backend import make_sandbox as _default_make_sandbox
from agent.sandbox.exceptions import SandboxCriticRejected
from agent.sandbox.policy import SandboxPolicy, get_policy

if TYPE_CHECKING:
    from agent.sandbox.registry import SandboxRegistry

log = get_logger(__name__)


async def exec_tool(
    command: list[str] | str,
    *,
    policy_name: str = "default",
    files: dict[str, bytes] | None = None,
    stdin: bytes | None = None,
    env: dict[str, str] | None = None,
    # Injeção de dependência (facilita testes)
    make_sandbox: Callable[[SandboxConfig], Sandbox] = _default_make_sandbox,
    critic: Any | None = None,
    registry: "SandboxRegistry | None" = None,
    mission_id: str | None = None,
    subagent_id: str | None = None,
) -> SandboxResult:
    """
    Executa um comando em uma sandbox isolada.

    Args:
        command: Comando como string ("python -c '...'") ou lista (["python", "-c", "..."]).
        policy_name: Nome da política registrada em sandbox/policy.py.
        files: Arquivos a injetar no workdir antes da execução {nome: bytes}.
        stdin: Bytes para stdin do processo.
        env: Variáveis de ambiente adicionais (complementa o mínimo da sandbox).
        make_sandbox: Factory para criar a instância de Sandbox (injetável em testes).
        critic: Instância de Critic para políticas com require_critic_approval=True.
        registry: SandboxRegistry para persistência de execuções.
        mission_id: ID da missão pai (rastreabilidade).
        subagent_id: ID do subagente pai (rastreabilidade).

    Returns:
        SandboxResult com exit_code, stdout, stderr, métricas e files_out.

    Raises:
        SandboxCriticRejected: Se política require_critic_approval=True e Crítico rejeitou.
        KeyError: Se policy_name não existe no registry.
    """
    policy = get_policy(policy_name)

    # Gate explícito: NetworkPolicy.OPEN requer allow_open_network=True na política
    from agent.sandbox.base import NetworkPolicy
    if policy.config.network == NetworkPolicy.OPEN and not policy.allow_open_network:
        raise ValueError(
            f"Política '{policy.name}' usa NetworkPolicy.OPEN mas allow_open_network=False. "
            "Defina allow_open_network=True na SandboxPolicy para permitir rede aberta."
        )

    # Aprovação pelo Crítico se política exige
    if policy.require_critic_approval and critic is not None:
        result = await _request_critic_approval(command, policy, critic)
        if result is not None:
            # Crítico rejeitou — retorna resultado de rejeição sem executar
            return result

    sandbox_id = None
    if registry is not None:
        sandbox_id = registry.new_id()
        backend_name = make_sandbox.__module__.split(".")[-1].replace("_backend", "")
        registry.mark_started(sandbox_id, policy_name, backend_name, command)
        await _emit_started(sandbox_id, policy_name, backend_name, command)

    sandbox = make_sandbox(policy.config)
    try:
        result = await sandbox.run(command, files=files, stdin=stdin, env=env)
    finally:
        await sandbox.cleanup()
        if registry is not None and sandbox_id is not None:
            registry.mark_done(sandbox_id)
            backend_name = make_sandbox.__module__.split(".")[-1].replace("_backend", "")
            await registry.record(
                sandbox_id=sandbox_id,
                policy_name=policy_name,
                backend=backend_name,
                command=command,
                result=result,
                mission_id=mission_id,
                subagent_id=subagent_id,
            )
            await _emit_finished(sandbox_id, result)
            if result.network_denied_attempts:
                await _emit_network_denied(sandbox_id, result.network_denied_attempts)
            if result.timed_out or result.oom_killed:
                await _emit_limit_exceeded(sandbox_id, result)

    log.info(
        "exec_tool.done",
        policy=policy_name,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        oom_killed=result.oom_killed,
    )
    return result


async def _request_critic_approval(
    command: list[str] | str,
    policy: SandboxPolicy,
    critic: Any,
) -> SandboxResult | None:
    """
    Enfileira no Crítico. Retorna SandboxResult de rejeição se rejeitado, None se aprovado.
    """
    approved = await critic.request_approval(
        command=command,
        policy_name=policy.name,
    )
    if not approved:
        cmd_preview = command if isinstance(command, str) else " ".join(command)
        log.info("exec_tool.critic_rejected", command_preview=cmd_preview[:100])
        return SandboxResult(
            exit_code=-1,
            stdout="",
            stderr=f"critic_rejected: execução bloqueada pela política {policy.name!r}",
            duration_ms=0,
            cpu_seconds=0.0,
            memory_peak_mb=0.0,
            timed_out=False,
            oom_killed=False,
            network_denied_attempts=[],
        )
    return None


async def _emit_started(sandbox_id: str, policy: str, backend: str, command: list[str] | str) -> None:
    import hashlib
    raw = command if isinstance(command, str) else " ".join(command)
    command_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    try:
        from agent.events import emit_sandbox_event
        await emit_sandbox_event("sandbox.execution.started", {
            "sandbox_id": sandbox_id,
            "policy": policy,
            "backend": backend,
            "command_hash": command_hash,
        })
    except Exception:
        pass


async def _emit_finished(sandbox_id: str, result: "SandboxResult") -> None:
    try:
        from agent.events import emit_sandbox_event
        await emit_sandbox_event("sandbox.execution.finished", {
            "sandbox_id": sandbox_id,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "memory_peak_mb": result.memory_peak_mb,
            "timed_out": result.timed_out,
            "oom_killed": result.oom_killed,
        })
    except Exception:
        pass


async def _emit_network_denied(sandbox_id: str, domains: list[str]) -> None:
    try:
        from agent.events import emit_sandbox_event
        for domain in domains:
            await emit_sandbox_event("sandbox.network.denied", {
                "sandbox_id": sandbox_id,
                "domain": domain,
            })
    except Exception:
        pass


async def _emit_limit_exceeded(sandbox_id: str, result: "SandboxResult") -> None:
    try:
        from agent.events import emit_sandbox_event
        if result.timed_out:
            await emit_sandbox_event("sandbox.limit.exceeded", {
                "sandbox_id": sandbox_id,
                "limit_type": "wall_time",
                "value": result.duration_ms,
            })
        if result.oom_killed:
            await emit_sandbox_event("sandbox.limit.exceeded", {
                "sandbox_id": sandbox_id,
                "limit_type": "memory",
                "value": result.memory_peak_mb,
            })
    except Exception:
        pass
