"""
Cobre §8 critérios 1, 2, 6, 7 (exec_tool E2E):
- exec_tool é o único ponto de execução.
- Linha gravada em sandbox_executions por execução.
- Log de output gerado em logs/sandbox/.
- Eventos sandbox.* emitidos.
- Crítico integrado: aprovação destrava, rejeição retorna exit_code=-1.
- preview de comando truncado em 200 chars.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent.sandbox.base import NetworkPolicy, SandboxConfig, SandboxResult
from agent.sandbox.subprocess_backend import SubprocessSandbox
from tests.sandbox.conftest import make_subprocess_sandbox


# ---------------------------------------------------------------------------
# Execução básica via exec_tool
# ---------------------------------------------------------------------------

async def test_exec_tool_runs_command():
    from agent.tools.exec_tool import exec_tool

    result = await exec_tool(
        "echo exec_tool_ok",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
    )
    assert result.exit_code == 0
    assert "exec_tool_ok" in result.stdout


async def test_exec_tool_list_command():
    from agent.tools.exec_tool import exec_tool

    result = await exec_tool(
        ["echo", "list_ok"],
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
    )
    assert result.exit_code == 0
    assert "list_ok" in result.stdout


async def test_exec_tool_unknown_policy_raises():
    from agent.tools.exec_tool import exec_tool

    with pytest.raises(KeyError):
        await exec_tool(
            "echo test",
            policy_name="nonexistent_xyz",
            make_sandbox=make_subprocess_sandbox,
        )


# ---------------------------------------------------------------------------
# Persistência no banco (requer Postgres)
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_exec_tool_writes_db_row(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.tools.exec_tool import exec_tool

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    result = await exec_tool(
        "echo db_row_test",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    row = await tmpdb.fetchrow("SELECT * FROM sandbox_executions LIMIT 1")
    assert row is not None
    assert row["policy_name"] == "default"
    assert row["exit_code"] == 0
    assert "echo db_row_test" in row["command_preview"]


@pytest.mark.integration
async def test_exec_tool_stores_mission_and_subagent_ids(tmpdb, tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.tools.exec_tool import exec_tool

    reg = SandboxRegistry(db_pool=tmpdb, log_dir=tmp_log_dir)
    await exec_tool(
        "echo tracking",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
        mission_id="mission-abc",
        subagent_id="subagent-xyz",
    )

    row = await tmpdb.fetchrow("SELECT mission_id, subagent_id FROM sandbox_executions")
    assert row["mission_id"] == "mission-abc"
    assert row["subagent_id"] == "subagent-xyz"


# ---------------------------------------------------------------------------
# Logs em arquivo
# ---------------------------------------------------------------------------

async def test_exec_tool_writes_log_files(tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.tools.exec_tool import exec_tool

    reg = SandboxRegistry(db_pool=None, log_dir=tmp_log_dir)
    await exec_tool(
        "echo log_file_test",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    # Deve existir pelo menos 1 arquivo .out
    out_files = list(tmp_log_dir.rglob("*.out"))
    assert len(out_files) >= 1
    content = out_files[0].read_text()
    assert "log_file_test" in content


# ---------------------------------------------------------------------------
# Preview de comando truncado em 200 chars
# ---------------------------------------------------------------------------

async def test_exec_tool_command_preview_truncated(tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry
    from agent.tools.exec_tool import exec_tool

    long_cmd = "echo " + "x" * 500   # 505 chars
    reg = SandboxRegistry(db_pool=None, log_dir=tmp_log_dir)

    sid = reg.new_id()
    reg.mark_started(sid, "default", "subprocess", long_cmd)
    active = reg._active[sid]
    assert len(active["command_preview"]) <= 200


# ---------------------------------------------------------------------------
# Eventos emitidos
# ---------------------------------------------------------------------------

async def test_exec_tool_emits_started_and_finished(event_collector):
    from agent.tools.exec_tool import exec_tool
    from agent.sandbox.registry import SandboxRegistry
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        reg = SandboxRegistry(db_pool=None, log_dir=Path(tmp))
        await exec_tool(
            "echo events_test",
            policy_name="default",
            make_sandbox=make_subprocess_sandbox,
            registry=reg,
        )

    types = [e["type"] for e in event_collector]
    assert "sandbox.execution.started" in types
    assert "sandbox.execution.finished" in types


async def test_exec_tool_started_event_has_required_fields(event_collector):
    from agent.tools.exec_tool import exec_tool
    from agent.sandbox.registry import SandboxRegistry
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        reg = SandboxRegistry(db_pool=None, log_dir=Path(tmp))
        await exec_tool(
            "echo fields_test",
            policy_name="default",
            make_sandbox=make_subprocess_sandbox,
            registry=reg,
        )

    started = next(e for e in event_collector if e["type"] == "sandbox.execution.started")
    assert "sandbox_id" in started["data"]
    assert "policy" in started["data"]
    assert "backend" in started["data"]
    assert "command_hash" in started["data"]


async def test_exec_tool_finished_event_has_required_fields(event_collector):
    from agent.tools.exec_tool import exec_tool
    from agent.sandbox.registry import SandboxRegistry
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        reg = SandboxRegistry(db_pool=None, log_dir=Path(tmp))
        await exec_tool(
            "echo finished_fields",
            policy_name="default",
            make_sandbox=make_subprocess_sandbox,
            registry=reg,
        )

    finished = next(e for e in event_collector if e["type"] == "sandbox.execution.finished")
    d = finished["data"]
    assert "sandbox_id" in d
    assert "exit_code" in d
    assert "duration_ms" in d
    assert "timed_out" in d
    assert "oom_killed" in d


# ---------------------------------------------------------------------------
# Crítico integrado
# ---------------------------------------------------------------------------

async def test_exec_tool_critic_approved_runs_command():
    """Com critic aprovando, exec_tool executa o comando normalmente."""
    from unittest.mock import AsyncMock
    from agent.tools.exec_tool import exec_tool

    mock_critic = AsyncMock()
    mock_critic.request_approval = AsyncMock(return_value=True)

    result = await exec_tool(
        "echo approved_run",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=mock_critic,
    )
    assert result.exit_code == 0
    assert "approved_run" in result.stdout
    mock_critic.request_approval.assert_awaited_once()


async def test_exec_tool_critic_rejected_returns_minus_one():
    """Com critic rejeitando, exec_tool retorna exit_code=-1 sem executar (§8 critério 5)."""
    from unittest.mock import AsyncMock
    from agent.tools.exec_tool import exec_tool

    mock_critic = AsyncMock()
    mock_critic.request_approval = AsyncMock(return_value=False)

    result = await exec_tool(
        "echo should_not_run",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=mock_critic,
    )
    assert result.exit_code == -1
    assert "critic_rejected" in result.stderr
    assert "should_not_run" not in result.stdout


async def test_exec_tool_untrusted_without_critic_runs():
    """Sem instância de critic, require_critic_approval é ignorado e execução prossegue."""
    from agent.tools.exec_tool import exec_tool

    result = await exec_tool(
        "echo no_critic",
        policy_name="untrusted",
        make_sandbox=make_subprocess_sandbox,
        critic=None,
    )
    assert result.exit_code == 0
    assert "no_critic" in result.stdout


# ---------------------------------------------------------------------------
# Timeout via exec_tool
# ---------------------------------------------------------------------------

async def test_exec_tool_timeout_propagates():
    """Timeout interno da sandbox chega ao chamador via SandboxResult.timed_out."""
    from tests.sandbox.conftest import make_subprocess_sandbox as f
    from agent.tools.exec_tool import exec_tool
    from agent.sandbox.base import SandboxConfig, NetworkPolicy
    from agent.sandbox.subprocess_backend import SubprocessSandbox

    def _fast_sandbox(cfg: SandboxConfig) -> SubprocessSandbox:
        return SubprocessSandbox(SandboxConfig(
            wall_time_seconds=1,
            network=NetworkPolicy.DENY_ALL,
        ))

    result = await exec_tool(
        "sleep 10",
        policy_name="default",
        make_sandbox=_fast_sandbox,
    )
    assert result.timed_out is True
