"""
Cobre §8 critério 7: eventos sandbox.* emitidos no event_registry.
- Todos os 4 tipos emitidos no happy path (com registry).
- sandbox.limit.exceeded emitido em timeout.
- Nenhum evento extra em execução limpa sem registry.
- Payload dos eventos válido.
"""

from __future__ import annotations

import pytest

from tests.sandbox.conftest import make_subprocess_sandbox


def _make_registry(tmp_log_dir):
    from agent.sandbox.registry import SandboxRegistry

    return SandboxRegistry(db_pool=None, log_dir=tmp_log_dir)


# ---------------------------------------------------------------------------
# Happy path: started + finished emitidos
# ---------------------------------------------------------------------------


async def test_happy_path_emits_started_and_finished(event_collector, tmp_path):
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo events_happy",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    types = [e["type"] for e in event_collector]
    assert "sandbox.execution.started" in types
    assert "sandbox.execution.finished" in types


async def test_happy_path_no_limit_exceeded_event(event_collector, tmp_path):
    """Execução limpa não deve emitir sandbox.limit.exceeded."""
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo no_limit",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    limit_events = [e for e in event_collector if e["type"] == "sandbox.limit.exceeded"]
    assert limit_events == []


async def test_happy_path_no_network_denied_event(event_collector, tmp_path):
    """Execução sem tentativas de rede não emite sandbox.network.denied."""
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo no_network",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    network_events = [e for e in event_collector if e["type"] == "sandbox.network.denied"]
    assert network_events == []


# ---------------------------------------------------------------------------
# Timeout → sandbox.limit.exceeded emitido
# ---------------------------------------------------------------------------


async def test_timeout_emits_limit_exceeded(event_collector, tmp_path):
    """Timeout deve emitir sandbox.limit.exceeded com limit_type=wall_time."""
    from agent.sandbox.base import NetworkPolicy, SandboxConfig
    from agent.sandbox.subprocess_backend import SubprocessSandbox
    from agent.tools.exec_tool import exec_tool

    def _timeout_factory(cfg: SandboxConfig) -> SubprocessSandbox:
        return SubprocessSandbox(
            SandboxConfig(
                wall_time_seconds=1,
                network=NetworkPolicy.DENY_ALL,
            )
        )

    reg = _make_registry(tmp_path)
    result = await exec_tool(
        "sleep 10",
        policy_name="default",
        make_sandbox=_timeout_factory,
        registry=reg,
    )

    assert result.timed_out is True

    limit_events = [e for e in event_collector if e["type"] == "sandbox.limit.exceeded"]
    assert len(limit_events) >= 1
    assert any(e["data"].get("limit_type") == "wall_time" for e in limit_events)


# ---------------------------------------------------------------------------
# Sem registry → nenhum evento emitido
# ---------------------------------------------------------------------------


async def test_no_registry_no_events(event_collector):
    """Sem registry, exec_tool não emite eventos (registry=None = sem ID)."""
    from agent.tools.exec_tool import exec_tool

    await exec_tool(
        "echo no_registry",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=None,
    )

    assert event_collector == []


# ---------------------------------------------------------------------------
# Ordem dos eventos
# ---------------------------------------------------------------------------


async def test_started_event_precedes_finished(event_collector, tmp_path):
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo order_test",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    types = [e["type"] for e in event_collector]
    started_idx = next(i for i, t in enumerate(types) if t == "sandbox.execution.started")
    finished_idx = next(i for i, t in enumerate(types) if t == "sandbox.execution.finished")
    assert started_idx < finished_idx


# ---------------------------------------------------------------------------
# Payload de sandbox.execution.started
# ---------------------------------------------------------------------------


async def test_started_event_payload(event_collector, tmp_path):
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo payload_check",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    started = next(e for e in event_collector if e["type"] == "sandbox.execution.started")
    d = started["data"]
    assert "sandbox_id" in d
    assert "policy" in d
    assert d["policy"] == "default"
    assert "backend" in d
    assert "command_hash" in d
    assert len(d["command_hash"]) == 16  # sha256[:16]


# ---------------------------------------------------------------------------
# Payload de sandbox.execution.finished
# ---------------------------------------------------------------------------


async def test_finished_event_payload(event_collector, tmp_path):
    from agent.tools.exec_tool import exec_tool

    reg = _make_registry(tmp_path)
    await exec_tool(
        "echo payload_finished",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
        registry=reg,
    )

    finished = next(e for e in event_collector if e["type"] == "sandbox.execution.finished")
    d = finished["data"]
    assert d["exit_code"] == 0
    assert d["timed_out"] is False
    assert d["oom_killed"] is False
    assert d["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# AgentEvent.type aceita tipos sandbox.*
# ---------------------------------------------------------------------------


def test_agent_event_accepts_sandbox_types():
    from agent.events import AgentEvent

    for event_type in [
        "sandbox.execution.started",
        "sandbox.execution.finished",
        "sandbox.network.denied",
        "sandbox.limit.exceeded",
    ]:
        e = AgentEvent(type=event_type, data={"test": True})
        assert e.type == event_type


def test_agent_event_rejects_unknown_sandbox_type():
    from pydantic import ValidationError

    from agent.events import AgentEvent

    with pytest.raises(ValidationError):
        AgentEvent(type="sandbox.unknown.event", data={})
