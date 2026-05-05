"""
Executa uma skill: renderiza o prompt Jinja2, chama o LLM e,
se a skill declarar tools, executa as tool_calls que o LLM produzir.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, StrictUndefined, TemplateError, UndefinedError

from agent.observability.logger import get_logger
from agent.skills.schema import SkillError, SkillManifest, SkillResult

if TYPE_CHECKING:
    from agent.tools.registry import ToolRegistry
    from agent.transports.base import BaseTransport

log = get_logger(__name__)

_jinja_env = Environment(
    undefined=StrictUndefined,  # falha alto se argumento ausente
    autoescape=False,
)


def _render_prompt(template_str: str, arguments: dict[str, Any]) -> str:
    try:
        template = _jinja_env.from_string(template_str)
        return template.render(**arguments)
    except UndefinedError as exc:
        raise SkillError(f"Argumento ausente no template da skill: {exc}") from exc
    except TemplateError as exc:
        raise SkillError(f"Erro no template da skill: {exc}") from exc


def _fill_defaults(manifest: SkillManifest, arguments: dict[str, Any]) -> dict[str, Any]:
    """Injeta defaults para argumentos não fornecidos."""
    filled = dict(arguments)
    for arg in manifest.arguments:
        if arg.name not in filled and arg.default is not None:
            filled[arg.name] = arg.default
    return filled


class SkillRunner:
    def __init__(
        self,
        transport: "BaseTransport",
        tool_registry: "ToolRegistry | None" = None,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry

    async def execute(self, manifest: SkillManifest, raw_arguments: dict[str, Any]) -> SkillResult:
        arguments = _fill_defaults(manifest, raw_arguments)
        system_prompt = _render_prompt(manifest.prompt, arguments)

        # Tools que esta skill pode invocar
        tool_schemas: list[dict[str, Any]] = []
        if manifest.tools and self._tool_registry:
            for tool_name in manifest.tools:
                tool = self._tool_registry.get(tool_name)
                if tool:
                    tool_schemas.append(tool.to_anthropic_schema())
                else:
                    log.warning("skill.tool_not_found", skill=manifest.name, tool=tool_name)

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"Execute a skill '{manifest.name}'."},
        ]

        try:
            response = await self._transport.chat(
                system=system_prompt,
                messages=messages,
                tools=tool_schemas or None,
                max_tokens=2048,
            )
        except Exception as exc:
            raise SkillError(f"LLM falhou ao executar skill '{manifest.name}': {exc}") from exc

        # Executar tool_calls do LLM (se houver)
        if response.tool_calls and self._tool_registry:
            tool_results = await self._execute_tool_calls(response.tool_calls, manifest.name)
            messages.append(self._build_assistant_message(response.text, response.tool_calls))
            messages.append({"role": "user", "content": tool_results})

            # Segunda chamada ao LLM com os resultados das tools
            try:
                response = await self._transport.chat(
                    system=system_prompt,
                    messages=messages,
                    tools=None,
                    max_tokens=2048,
                )
            except Exception as exc:
                raise SkillError(f"LLM falhou na segunda chamada da skill '{manifest.name}': {exc}") from exc

        return SkillResult(
            skill_name=manifest.name,
            skill_version=manifest.version,
            output=response.text,
            success=True,
        )

    async def _execute_tool_calls(
        self, tool_calls: list[dict[str, Any]], skill_name: str
    ) -> list[dict[str, Any]]:
        if not self._tool_registry:
            return []

        results = []
        for call in tool_calls:
            name = call["name"]
            args = call.get("input", {})
            tool_result = await self._tool_registry.execute(name, args)
            results.append({
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": (
                    json.dumps(tool_result.output, ensure_ascii=False)
                    if tool_result.ok
                    else f"ERROR: {tool_result.error}"
                ),
            })
            if not tool_result.ok:
                log.warning(
                    "skill.tool_call.failed",
                    skill=skill_name,
                    tool=name,
                    error=tool_result.error,
                )
        return results

    @staticmethod
    def _build_assistant_message(
        text: str, tool_calls: list[dict[str, Any]]
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for call in tool_calls:
            content.append({
                "type": "tool_use",
                "id": call["id"],
                "name": call["name"],
                "input": call.get("input", {}),
            })
        return {"role": "assistant", "content": content}
