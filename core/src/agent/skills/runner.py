"""
SkillRunner (Fase 9): executa skills auto-geradas via exec_tool (F8).

Single entry point: TODA execução de skill passa por exec_tool.
Sem bypass do sandbox — toda execução via exec_tool.

Fluxo:
  1. Carrega manifest do registry
  2. Valida input contra inputs_schema
  3. Monta SandboxPolicy do manifesto
  4. Executa via exec_tool com script skill_runtime
  5. Valida output contra outputs_schema
  6. Atualiza stats + emite evento
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger
from agent.skills.exceptions import (
    SkillInputInvalid,
    SkillNotActive,
    SkillNotFound,
    SkillOutputInvalid,
)

if TYPE_CHECKING:
    from agent.sandbox.base import SandboxResult
    from agent.skills.manifest import SkillManifestF9
    from agent.skills.registry import SkillRegistry

log = get_logger(__name__)

# Script que roda dentro do sandbox: carrega skill.py, chama run(input), imprime JSON
_RUNTIME_SCRIPT = """\
import asyncio, json, sys, importlib.util
spec = importlib.util.spec_from_file_location('skill', 'skill.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
raw = open('input.json').read()
data = json.loads(raw)
result = asyncio.run(mod.run(data))
print(json.dumps(result))
"""


@dataclass
class SkillRunResult:
    slug: str
    output: dict[str, Any]
    sandbox_result: "SandboxResult"
    execution_id: str
    duration_seconds: float


class SkillRunner:
    def __init__(
        self,
        registry: "SkillRegistry",
        skills_active_dir: Any,  # Path
        exec_tool_fn: Any = None,
        sandbox_registry: Any = None,
    ) -> None:
        self._registry = registry
        self._active_dir = skills_active_dir
        self._exec_tool = exec_tool_fn
        self._sandbox_registry = sandbox_registry

    async def run_skill(
        self,
        slug: str,
        input_data: dict[str, Any],
        *,
        mission_id: str | None = None,
    ) -> SkillRunResult:
        """Executa skill ativa. Lança SkillNotFound, SkillNotActive, SkillInputInvalid."""
        row = await self._registry.get(slug)
        if row["status"] != "active":
            raise SkillNotActive(slug, row["status"])

        manifest_data = json.loads(row["manifest_json"])
        from agent.skills.manifest import SkillManifestF9
        manifest = SkillManifestF9(**manifest_data)

        _validate_input(input_data, manifest.inputs_schema, slug)

        skill_dir = self._active_dir / slug
        skill_py = skill_dir / "skill.py"
        if not skill_py.exists():
            raise SkillNotFound(slug)

        policy_name = _manifest_profile_to_policy(manifest.sandbox_profile)
        files: dict[str, bytes] = {
            "skill.py": skill_py.read_bytes(),
            "input.json": json.dumps(input_data).encode(),
            "runtime.py": _RUNTIME_SCRIPT.encode(),
        }

        t0 = time.monotonic()
        sandbox_result = await self._exec_tool(
            ["python", "runtime.py"],
            policy_name=policy_name,
            files=files,
            mission_id=mission_id,
            registry=self._sandbox_registry,
        )
        duration = time.monotonic() - t0

        success = sandbox_result.exit_code == 0
        output: dict[str, Any] = {}
        error_msg: str | None = None

        if success:
            try:
                output = json.loads(sandbox_result.stdout.strip())
                _validate_output(output, manifest.outputs_schema, slug)
            except (json.JSONDecodeError, SkillOutputInvalid) as exc:
                success = False
                error_msg = str(exc)
        else:
            error_msg = sandbox_result.stderr[:500] or f"exit_code={sandbox_result.exit_code}"

        exec_id = await self._registry.record_execution(
            slug,
            success=success,
            duration_seconds=duration,
            mission_id=mission_id,
            input_data=input_data,
            output_data=output if success else None,
            error_message=error_msg,
        )

        await _emit_skill_event("skill.executed", {
            "slug": slug,
            "success": success,
            "duration": duration,
            "mission_id": mission_id,
        })

        if not success:
            raise RuntimeError(f"Skill '{slug}' falhou: {error_msg}")

        return SkillRunResult(
            slug=slug,
            output=output,
            sandbox_result=sandbox_result,
            execution_id=exec_id,
            duration_seconds=duration,
        )


def _manifest_profile_to_policy(profile: str) -> str:
    mapping = {
        "SKILL_DEV": "skill_dev",
        "DEFAULT": "default",
        "UNTRUSTED": "untrusted",
    }
    return mapping.get(profile, "default")


def _validate_input(data: dict[str, Any], schema: dict[str, Any], slug: str) -> None:
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in data:
            raise SkillInputInvalid(slug, f"campo obrigatório '{field_name}' ausente")


def _validate_output(data: Any, schema: dict[str, Any], slug: str) -> None:
    if not isinstance(data, dict):
        raise SkillOutputInvalid(slug, f"output deve ser dict, got {type(data).__name__}")
    required = schema.get("required", [])
    for field_name in required:
        if field_name not in data:
            raise SkillOutputInvalid(slug, f"campo obrigatório '{field_name}' ausente no output")


async def _emit_skill_event(event_type: str, data: dict[str, Any]) -> None:
    try:
        from agent.events import emit_skill_event
        await emit_skill_event(event_type, data)
    except Exception:
        pass
