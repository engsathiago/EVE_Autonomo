"""
Cobre §8 critério 5: POLICY_UNTRUSTED integra com Crítico.
- Aprovação destrava execução.
- Rejeição retorna exit_code=-1 com razão em stderr.
- Sem critic, execução prossegue (graceful degradation).
- request_approval é chamado exatamente uma vez por exec_tool.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from tests.sandbox.conftest import make_subprocess_sandbox

# ---------------------------------------------------------------------------
# Aprovação do Crítico → executa
# ---------------------------------------------------------------------------

async def test_untrusted_critic_approved_executes():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=True)

    result = await exec_tool(
        "echo critic_approved",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    assert result.exit_code == 0
    assert "critic_approved" in result.stdout
    critic.request_approval.assert_awaited_once()


# ---------------------------------------------------------------------------
# Rejeição do Crítico → exit_code=-1 com razão
# ---------------------------------------------------------------------------

async def test_untrusted_critic_rejected_returns_minus_one():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=False)

    result = await exec_tool(
        "echo should_not_execute",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    assert result.exit_code == -1
    assert "critic_rejected" in result.stderr
    assert result.stdout == ""


async def test_critic_rejection_stderr_contains_policy_name():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=False)

    result = await exec_tool(
        "echo test",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    assert "untrusted" in result.stderr


# ---------------------------------------------------------------------------
# Sem critic → execução prossegue (graceful)
# ---------------------------------------------------------------------------

async def test_untrusted_without_critic_runs():
    from agent.tools.exec_tool import exec_tool

    result = await exec_tool(
        "echo no_critic_degraded",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=None,
    )

    assert result.exit_code == 0
    assert "no_critic_degraded" in result.stdout


# ---------------------------------------------------------------------------
# Política default → critic nunca é chamado
# ---------------------------------------------------------------------------

async def test_default_policy_critic_not_called():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=True)

    await exec_tool(
        "echo default_no_critic",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    # Política default não tem require_critic_approval=True
    critic.request_approval.assert_not_awaited()


# ---------------------------------------------------------------------------
# Métricas: rejeitado tem duration_ms=0 (não executou)
# ---------------------------------------------------------------------------

async def test_critic_rejected_result_has_zero_duration():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=False)

    result = await exec_tool(
        "sleep 999",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    assert result.duration_ms == 0
    assert result.timed_out is False
    assert result.oom_killed is False


# ---------------------------------------------------------------------------
# request_approval recebe command e policy_name corretos
# ---------------------------------------------------------------------------

async def test_critic_receives_correct_args():
    from agent.tools.exec_tool import exec_tool

    critic = MagicMock()
    critic.request_approval = AsyncMock(return_value=True)

    await exec_tool(
        "echo args_check",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=critic,
    )

    call_kwargs = critic.request_approval.call_args.kwargs
    assert "command" in call_kwargs
    assert call_kwargs["policy_name"] == "untrusted"
