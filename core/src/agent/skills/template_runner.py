"""
TemplateSkillRunner: executa skills da Fase 3 (.md templates via Jinja2 + LLM).

Fase 9 usa SkillRunner (runner.py) para skills auto-geradas (.py via sandbox).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, StrictUndefined, TemplateError, UndefinedError

from agent.observability.logger import get_logger
from agent.skills.schema import SkillError, SkillManifest, SkillResult

if TYPE_CHECKING:
    from agent.approvals.manager import ApprovalManager, ApprovalRequest
    from agent.models.router import ModelRouter
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


def _render_approval_summary(manifest: SkillManifest, arguments: dict[str, Any]) -> str:
    template = getattr(manifest, "approval_summary_template", None)
    if template:
        try:
            return _jinja_env.from_string(template).render(**arguments)
        except Exception:
            pass
    args_text = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
    return f"Executar skill '{manifest.name}' com args: {args_text}"


class TemplateSkillRunner:
    def __init__(
        self,
        transport: "BaseTransport",
        tool_registry: "ToolRegistry | None" = None,
        model_router: "ModelRouter | None" = None,
        approval_manager: "ApprovalManager | None" = None,
    ) -> None:
        self._transport = transport
        self._tool_registry = tool_registry
        self._model_router = model_router
        self._approval_manager = approval_manager

    async def execute(
        self,
        manifest: SkillManifest,
        raw_arguments: dict[str, Any],
        session_id: str | None = None,
        channel: str = "cli",
        channel_ref: dict[str, Any] | None = None,
    ) -> "SkillResult | ApprovalRequest":
        if manifest.requires_approval:
            if self._approval_manager is None:
                raise SkillError(
                    f"Skill '{manifest.name}' requires_approval=True mas ApprovalManager não está configurado."
                )
            summary = _render_approval_summary(manifest, raw_arguments)
            return await self._approval_manager.create(
                session_id=session_id or "cli",
                skill_name=manifest.name,
                skill_args=raw_arguments,
                summary=summary,
                channel=channel,
                channel_ref=channel_ref,
            )

        return await self._run_skill(manifest, raw_arguments)

    async def execute_approved(
        self,
        approval_id: str,
        manifest: SkillManifest,
    ) -> SkillResult:
        """Executa uma skill após aprovação humana. Busca os args originais do approval."""
        if self._approval_manager is None:
            raise SkillError("ApprovalManager não está configurado.")

        from agent.approvals.manager import ApprovalNotFoundError

        state = await self._approval_manager.get(approval_id)
        if state.status != "approved":
            raise SkillError(f"Approval {approval_id!r} não está aprovado (status={state.status!r}).")

        return await self._run_skill(manifest, state.skill_args)

    async def _run_skill(self, manifest: SkillManifest, raw_arguments: dict[str, Any]) -> SkillResult:
        """Núcleo de execução (sem verificação de approval)."""
        arguments = _fill_defaults(manifest, raw_arguments)
        system_prompt = _render_prompt(manifest.prompt, arguments)

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
            response = await self._chat(
                system=system_prompt,
                messages=messages,
                tools=tool_schemas or None,
                max_tokens=2048,
                model=manifest.model,
            )
        except Exception as exc:
            raise SkillError(f"LLM falhou ao executar skill '{manifest.name}': {exc}") from exc

        if response.tool_calls and self._tool_registry:
            tool_results = await self._execute_tool_calls(response.tool_calls, manifest.name)
            messages.append(self._build_assistant_message(response.text, response.tool_calls))
            messages.append({"role": "user", "content": tool_results})

            try:
                response = await self._chat(
                    system=system_prompt,
                    messages=messages,
                    tools=None,
                    max_tokens=2048,
                    model=manifest.model,
                )
            except Exception as exc:
                raise SkillError(
                    f"LLM falhou na segunda chamada da skill '{manifest.name}': {exc}"
                ) from exc

        return SkillResult(
            skill_name=manifest.name,
            skill_version=manifest.version,
            output=response.text,
            success=True,
        )

    async def _chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        model: str | None,
    ) -> Any:
        if self._model_router is not None:
            return await self._model_router.chat(
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                model=model,
            )
        return await self._transport.chat(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
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
