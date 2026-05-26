"""
SkillValidator (Fase 9): lint + testes + smoke run em sandbox SKILL_DEV.

Fluxo:
  1. Syntax check via ast.parse (sem execução de código)
  2. Parse + validação do manifest.yaml
  3. Assinatura: async def run(input: dict) -> dict
  4. Lint check via exec_tool (ruff delegado ao sandbox — C7 compliant)
  5. Smoke run com input sintético em sandbox SKILL_DEV

Falhou em qualquer etapa → ValidationReport.passed=False com motivo.
Execução delega para exec_tool (C7 compliant).
"""

from __future__ import annotations

import ast
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.observability.logger import get_logger
from agent.skills.manifest import SkillManifestF9, load_manifest_from_yaml

log = get_logger(__name__)


@dataclass
class ValidationReport:
    slug: str
    passed: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None

    def add_step(self, name: str, *, ok: bool, detail: str = "") -> None:
        self.steps.append({"step": name, "ok": ok, "detail": detail})
        if not ok and self.failure_reason is None:
            self.failure_reason = f"{name}: {detail}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "passed": self.passed,
            "steps": self.steps,
            "failure_reason": self.failure_reason,
        }


class SkillValidator:
    def __init__(self, skill_dir: Path, exec_tool_fn: Any = None) -> None:
        self._skill_dir = skill_dir
        self._exec_tool = exec_tool_fn  # callable async: exec_tool(cmd, policy_name=...)

    async def validate(self, manifest: SkillManifestF9) -> ValidationReport:
        """
        Valida skill candidata. Retorna ValidationReport com passed=True/False.
        Todo lint e execução passa por exec_tool ou ast — zero invocação de processo
        direta neste módulo (C7).
        """
        slug = manifest.slug
        skill_py = self._skill_dir / "skill.py"
        manifest_yaml = self._skill_dir / "manifest.yaml"

        report = ValidationReport(slug=slug, passed=False)

        # 1. Arquivos obrigatórios
        if not skill_py.exists():
            report.add_step("files_exist", ok=False, detail="skill.py não encontrado")
            return report
        report.add_step("files_exist", ok=True)

        # 2. Syntax check via ast.parse (sem execução, sem fork)
        syntax_ok, syntax_detail = _check_syntax(skill_py)
        report.add_step("syntax_check", ok=syntax_ok, detail=syntax_detail)
        if not syntax_ok:
            return report

        # 3. Assinatura: async def run(input: dict) -> dict
        sig_ok, sig_detail = _check_signature(skill_py)
        report.add_step("signature_check", ok=sig_ok, detail=sig_detail)
        if not sig_ok:
            return report

        # 4. Manifest parse + validação Pydantic
        try:
            loaded = load_manifest_from_yaml(manifest_yaml)
            report.add_step("manifest_valid", ok=True)
        except Exception as exc:
            report.add_step("manifest_valid", ok=False, detail=str(exc))
            return report

        # 5. Lint via exec_tool (ruff inside sandbox — invocação no sandbox, não aqui)
        if self._exec_tool is not None:
            lint_ok, lint_detail = await self._lint_via_sandbox(skill_py)
            report.add_step("ruff_lint", ok=lint_ok, detail=lint_detail)
            if not lint_ok:
                return report
        else:
            report.add_step("ruff_lint", ok=True, detail="skipped (no exec_tool)")

        # 6. Smoke run via exec_tool (sandbox SKILL_DEV)
        if self._exec_tool is not None:
            smoke_ok, smoke_detail = await self._smoke_run(skill_py, loaded)
            report.add_step("smoke_run", ok=smoke_ok, detail=smoke_detail)
            if not smoke_ok:
                return report
        else:
            report.add_step("smoke_run", ok=True, detail="skipped (no exec_tool)")

        report.passed = True
        return report

    async def _lint_via_sandbox(self, skill_py: Path) -> tuple[bool, str]:
        """
        Delega ruff para exec_tool. O comando roda no sandbox (não aqui).
        Retorna (ok, detail).
        """
        try:
            result = await self._exec_tool(
                ["ruff", "check", "skill.py", "--output-format=json"],
                policy_name="skill_dev",
                files={"skill.py": skill_py.read_bytes()},
            )
            if result.exit_code == 0:
                return True, ""
            return False, (result.stdout[:400] or result.stderr[:400])
        except Exception as exc:
            return False, f"lint_sandbox_error: {exc}"

    async def _smoke_run(self, skill_py: Path, manifest: SkillManifestF9) -> tuple[bool, str]:
        synthetic_input = _make_synthetic_input(manifest.inputs_schema)
        script = textwrap.dedent(f"""
            import asyncio, json, sys
            sys.path.insert(0, '.')
            import importlib.util
            spec = importlib.util.spec_from_file_location('skill', 'skill.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = asyncio.run(mod.run({json.dumps(synthetic_input)}))
            print(json.dumps(result))
        """).strip()

        try:
            sandbox_result = await self._exec_tool(
                ["python", "-c", script],
                policy_name="skill_dev",
                files={"skill.py": skill_py.read_bytes()},
            )
        except Exception as exc:
            return False, f"exec_tool falhou: {exc}"

        if sandbox_result.exit_code != 0:
            return False, f"exit_code={sandbox_result.exit_code}: {sandbox_result.stderr[:300]}"

        try:
            output = json.loads(sandbox_result.stdout.strip())
        except json.JSONDecodeError:
            return False, f"output não é JSON: {sandbox_result.stdout[:200]}"

        ok, detail = _validate_against_schema(output, manifest.outputs_schema)
        return ok, detail


def _check_syntax(skill_py: Path) -> tuple[bool, str]:
    """Verifica sintaxe Python via ast.parse — sem execução, sem fork."""
    try:
        ast.parse(skill_py.read_text(encoding="utf-8"))
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError linha {exc.lineno}: {exc.msg}"


def _check_signature(skill_py: Path) -> tuple[bool, str]:
    source = skill_py.read_text()
    if "async def run(" not in source:
        return False, "função pública 'async def run(input: dict) -> dict' não encontrada"
    return True, ""


def _make_synthetic_input(inputs_schema: dict[str, Any]) -> dict[str, Any]:
    """Gera input sintético baseado no inputs_schema (valores mínimos válidos)."""
    props = inputs_schema.get("properties", {})
    required = inputs_schema.get("required", [])
    result: dict[str, Any] = {}
    for key in required:
        prop = props.get(key, {})
        t = prop.get("type", "string")
        if t == "string":
            default = prop.get("default", "test_value")
            fmt = prop.get("format", "")
            result[key] = "https://example.com/test" if fmt == "uri" else str(default)
        elif t == "integer":
            result[key] = prop.get("default", 1)
        elif t == "number":
            result[key] = prop.get("default", 1.0)
        elif t == "boolean":
            result[key] = prop.get("default", False)
        elif t == "array":
            result[key] = []
        else:
            result[key] = {}
    return result


def _validate_against_schema(output: Any, schema: dict[str, Any]) -> tuple[bool, str]:
    required = schema.get("required", [])
    if not isinstance(output, dict):
        return False, f"output deve ser dict, got {type(output).__name__}"
    for field_name in required:
        if field_name not in output:
            return False, f"campo obrigatório '{field_name}' ausente no output"
    return True, ""
