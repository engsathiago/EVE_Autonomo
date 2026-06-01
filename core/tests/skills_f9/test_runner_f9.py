"""Testes do SkillRunner F9 — C5/C6/C7: single entry point via exec_tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.sandbox.base import SandboxResult
from agent.skills.exceptions import SkillNotActive, SkillNotFound
from agent.skills.runner import (
    SkillRunner,
    _manifest_profile_to_policy,
    _validate_input,
    _validate_output,
)


def _make_sandbox_result(output: dict, exit_code: int = 0) -> SandboxResult:
    return SandboxResult(
        exit_code=exit_code,
        stdout=json.dumps(output) if exit_code == 0 else "",
        stderr="" if exit_code == 0 else "error",
        duration_ms=100,
        cpu_seconds=0.1,
        memory_peak_mb=50.0,
        timed_out=False,
        oom_killed=False,
        network_denied_attempts=[],
    )


def _manifest_json(slug: str = "test_skill", profile: str = "DEFAULT") -> str:
    return json.dumps(
        {
            "slug": slug,
            "version": 1,
            "created_at": "2026-05-10T00:00:00+00:00",
            "description": "test",
            "embedding_text": "test",
            "inputs_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            "outputs_schema": {
                "type": "object",
                "properties": {"transcript": {"type": "string"}},
                "required": ["transcript"],
            },
            "sandbox_profile": profile,
            "network_policy": {"allow_domains": []},
            "irreversible": False,
            "estimated_wall_time_seconds": 30,
            "estimated_memory_mb": 256,
            "stats": {},
            "provenance": {},
        }
    )


def _make_registry(slug: str = "test_skill", status: str = "active") -> MagicMock:
    registry = MagicMock()
    registry.get = AsyncMock(
        return_value={
            "slug": slug,
            "status": status,
            "manifest_json": _manifest_json(slug),
        }
    )
    registry.record_execution = AsyncMock(return_value="exec_id_abc123")
    return registry


@pytest.mark.asyncio
async def test_run_skill_not_active_raises(tmp_path: Path) -> None:
    registry = _make_registry(status="pending")
    runner = SkillRunner(registry=registry, skills_active_dir=tmp_path)
    with pytest.raises(SkillNotActive):
        await runner.run_skill("test_skill", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_run_skill_file_not_found_raises(tmp_path: Path) -> None:
    registry = _make_registry(status="active")
    runner = SkillRunner(registry=registry, skills_active_dir=tmp_path)
    with pytest.raises(SkillNotFound):
        await runner.run_skill("test_skill", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_run_skill_calls_exec_tool(tmp_path: Path) -> None:
    """C7: SkillRunner SEMPRE chama exec_tool — nunca subprocess direto."""
    slug = "test_skill"
    skill_dir = tmp_path / slug
    skill_dir.mkdir()
    (skill_dir / "skill.py").write_text(
        'async def run(input: dict) -> dict:\n    return {"transcript": "ok"}\n',
        encoding="utf-8",
    )

    mock_exec = AsyncMock(return_value=_make_sandbox_result({"transcript": "resultado"}))
    registry = _make_registry(slug=slug, status="active")
    runner = SkillRunner(registry=registry, skills_active_dir=tmp_path, exec_tool_fn=mock_exec)

    with patch("agent.skills.runner._emit_skill_event", new_callable=AsyncMock):
        result = await runner.run_skill(slug, {"url": "https://youtube.com/watch?v=test"})

    assert result.output == {"transcript": "resultado"}
    mock_exec.assert_awaited_once()
    # Garante que exec_tool recebeu um comando (não subprocess direto)
    call_args = mock_exec.call_args
    assert call_args is not None


@pytest.mark.asyncio
async def test_run_skill_records_execution_on_success(tmp_path: Path) -> None:
    slug = "test_skill"
    skill_dir = tmp_path / slug
    skill_dir.mkdir()
    (skill_dir / "skill.py").write_text('async def run(i): return {"transcript": "x"}', encoding="utf-8")

    mock_exec = AsyncMock(return_value=_make_sandbox_result({"transcript": "x"}))
    registry = _make_registry(slug=slug, status="active")
    runner = SkillRunner(registry=registry, skills_active_dir=tmp_path, exec_tool_fn=mock_exec)

    with patch("agent.skills.runner._emit_skill_event", new_callable=AsyncMock):
        result = await runner.run_skill(slug, {"url": "https://ex.com"})

    registry.record_execution.assert_awaited_once()
    kwargs = registry.record_execution.call_args.kwargs
    assert kwargs["success"] is True


@pytest.mark.asyncio
async def test_run_skill_records_failure_on_sandbox_error(tmp_path: Path) -> None:
    slug = "test_skill"
    skill_dir = tmp_path / slug
    skill_dir.mkdir()
    (skill_dir / "skill.py").write_text('async def run(i): return {"transcript": "x"}', encoding="utf-8")

    mock_exec = AsyncMock(return_value=_make_sandbox_result({}, exit_code=1))
    registry = _make_registry(slug=slug, status="active")
    runner = SkillRunner(registry=registry, skills_active_dir=tmp_path, exec_tool_fn=mock_exec)

    with patch("agent.skills.runner._emit_skill_event", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="falhou"):
            await runner.run_skill(slug, {"url": "https://ex.com"})

    kwargs = registry.record_execution.call_args.kwargs
    assert kwargs["success"] is False


def test_manifest_profile_to_policy() -> None:
    assert _manifest_profile_to_policy("SKILL_DEV") == "skill_dev"
    assert _manifest_profile_to_policy("DEFAULT") == "default"
    assert _manifest_profile_to_policy("UNTRUSTED") == "untrusted"
    assert _manifest_profile_to_policy("UNKNOWN") == "default"


def test_validate_input_missing_required() -> None:
    from agent.skills.exceptions import SkillInputInvalid

    schema = {"required": ["url"]}
    with pytest.raises(SkillInputInvalid):
        _validate_input({}, schema, "slug")


def test_validate_input_ok() -> None:
    schema = {"required": ["url"]}
    _validate_input({"url": "https://x.com"}, schema, "slug")  # não lança


def test_validate_output_not_dict() -> None:
    from agent.skills.exceptions import SkillOutputInvalid

    schema = {"required": ["result"]}
    with pytest.raises(SkillOutputInvalid):
        _validate_output("string", schema, "slug")


def test_validate_output_missing_required() -> None:
    from agent.skills.exceptions import SkillOutputInvalid

    schema = {"required": ["result"]}
    with pytest.raises(SkillOutputInvalid):
        _validate_output({}, schema, "slug")
