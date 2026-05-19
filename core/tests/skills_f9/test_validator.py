"""Testes do SkillValidator — C3: validação em sandbox."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from agent.sandbox.base import SandboxResult
from agent.skills.manifest import SkillManifestF9
from agent.skills.validator import SkillValidator, _make_synthetic_input, _validate_against_schema


def _manifest(slug: str = "test_skill") -> SkillManifestF9:
    return SkillManifestF9(
        slug=slug,
        version=1,
        created_at=datetime.now(tz=timezone.utc),
        description="test",
        embedding_text="test",
        inputs_schema={"type": "object", "properties": {"url": {"type": "string", "format": "uri"}}, "required": ["url"]},
        outputs_schema={"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
        sandbox_profile="SKILL_DEV",
        network_policy={"allow_domains": []},
    )


def _manifest_yaml(tmp_path: Path) -> None:
    data = {
        "slug": "test_skill", "version": 1,
        "created_at": "2026-05-10T00:00:00+00:00",
        "description": "test", "embedding_text": "test",
        "inputs_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        "outputs_schema": {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
        "sandbox_profile": "SKILL_DEV",
        "network_policy": {"allow_domains": []},
        "irreversible": False,
    }
    (tmp_path / "manifest.yaml").write_text(yaml.dump(data), encoding="utf-8")


def _ok_sandbox_result(output: str = '{"result": "ok"}') -> SandboxResult:
    return SandboxResult(
        exit_code=0, stdout=output, stderr="",
        duration_ms=100, cpu_seconds=0.1, memory_peak_mb=50.0,
        timed_out=False, oom_killed=False, network_denied_attempts=[],
    )


def _fail_sandbox_result(exit_code: int = 1, stderr: str = "error") -> SandboxResult:
    return SandboxResult(
        exit_code=exit_code, stdout="", stderr=stderr,
        duration_ms=100, cpu_seconds=0.1, memory_peak_mb=50.0,
        timed_out=False, oom_killed=False, network_denied_attempts=[],
    )


@pytest.mark.asyncio
async def test_validate_missing_skill_py(tmp_path: Path) -> None:
    validator = SkillValidator(tmp_path)
    report = await validator.validate(_manifest())
    assert not report.passed
    assert any(s["step"] == "files_exist" and not s["ok"] for s in report.steps)


@pytest.mark.asyncio
async def test_validate_syntax_error(tmp_path: Path) -> None:
    """Código com erro de sintaxe falha em syntax_check (antes de chegar em ruff_lint)."""
    (tmp_path / "skill.py").write_text("def broken(: = !!!", encoding="utf-8")
    _manifest_yaml(tmp_path)

    validator = SkillValidator(tmp_path)
    report = await validator.validate(_manifest())
    assert not report.passed
    step = next((s for s in report.steps if s["step"] == "syntax_check"), None)
    assert step is not None and not step["ok"]


@pytest.mark.asyncio
async def test_validate_missing_async_run_signature(tmp_path: Path) -> None:
    (tmp_path / "skill.py").write_text("def run(input): return {}", encoding="utf-8")
    _manifest_yaml(tmp_path)

    validator = SkillValidator(tmp_path)
    report = await validator.validate(_manifest())
    assert not report.passed
    sig_step = next((s for s in report.steps if s["step"] == "signature_check"), None)
    assert sig_step is not None and not sig_step["ok"]


@pytest.mark.asyncio
async def test_validate_ruff_lint_failure_via_sandbox(tmp_path: Path) -> None:
    """ruff_lint sandbox retorna exit_code!=0 → falha."""
    (tmp_path / "skill.py").write_text(
        'async def run(input: dict) -> dict:\n    return {"result": "ok"}\n',
        encoding="utf-8",
    )
    _manifest_yaml(tmp_path)

    # lint falha, smoke nunca é chamado
    mock_exec = AsyncMock(return_value=_fail_sandbox_result(exit_code=1, stderr="E501 line too long"))
    validator = SkillValidator(tmp_path, exec_tool_fn=mock_exec)
    report = await validator.validate(_manifest())
    assert not report.passed
    lint_step = next((s for s in report.steps if s["step"] == "ruff_lint"), None)
    assert lint_step is not None and not lint_step["ok"]


@pytest.mark.asyncio
async def test_validate_smoke_run_success(tmp_path: Path) -> None:
    (tmp_path / "skill.py").write_text(
        'async def run(input: dict) -> dict:\n    return {"result": "ok"}\n',
        encoding="utf-8",
    )
    _manifest_yaml(tmp_path)

    # exec_tool é chamado 2x: lint (ok) e smoke (ok)
    mock_exec = AsyncMock(side_effect=[
        _ok_sandbox_result(""),         # lint ok (exit_code=0)
        _ok_sandbox_result('{"result": "value"}'),  # smoke ok
    ])
    validator = SkillValidator(tmp_path, exec_tool_fn=mock_exec)
    report = await validator.validate(_manifest())
    assert report.passed, f"Falhou: {report.failure_reason}"
    smoke_step = next((s for s in report.steps if s["step"] == "smoke_run"), None)
    assert smoke_step is not None and smoke_step["ok"]


@pytest.mark.asyncio
async def test_validate_smoke_run_failure(tmp_path: Path) -> None:
    (tmp_path / "skill.py").write_text(
        'async def run(input: dict) -> dict:\n    return {"result": "ok"}\n',
        encoding="utf-8",
    )
    _manifest_yaml(tmp_path)

    mock_exec = AsyncMock(side_effect=[
        _ok_sandbox_result(""),   # lint ok
        _fail_sandbox_result(exit_code=1, stderr="ModuleNotFoundError"),  # smoke fail
    ])
    validator = SkillValidator(tmp_path, exec_tool_fn=mock_exec)
    report = await validator.validate(_manifest())
    assert not report.passed


@pytest.mark.asyncio
async def test_validate_no_exec_tool_skips_lint_and_smoke(tmp_path: Path) -> None:
    """Sem exec_tool, lint e smoke são skipped mas manifest e signature são validados."""
    (tmp_path / "skill.py").write_text(
        'async def run(input: dict) -> dict:\n    return {"result": "ok"}\n',
        encoding="utf-8",
    )
    _manifest_yaml(tmp_path)

    validator = SkillValidator(tmp_path, exec_tool_fn=None)
    report = await validator.validate(_manifest())
    assert report.passed


def test_make_synthetic_input_required_fields() -> None:
    schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "format": "uri"},
            "count": {"type": "integer"},
            "flag": {"type": "boolean"},
        },
        "required": ["url", "count"],
    }
    result = _make_synthetic_input(schema)
    assert "url" in result
    assert "count" in result
    assert "flag" not in result  # não obrigatório
    assert result["url"].startswith("https://")
    assert isinstance(result["count"], int)


def test_validate_against_schema_missing_field() -> None:
    schema = {"type": "object", "properties": {}, "required": ["result"]}
    ok, detail = _validate_against_schema({}, schema)
    assert not ok
    assert "result" in detail


def test_validate_against_schema_ok() -> None:
    schema = {"type": "object", "properties": {}, "required": ["result"]}
    ok, _ = _validate_against_schema({"result": "x"}, schema)
    assert ok
