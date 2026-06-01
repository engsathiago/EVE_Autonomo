"""Testes do SkillRunner + SkillManager.run — Milestone C."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.skills.manager import SkillManager
from agent.skills.schema import (
    SkillArgument,
    SkillError,
    SkillManifest,
    SkillRequiresApproval,
)
from agent.skills.template_runner import TemplateSkillRunner as SkillRunner
from agent.skills.template_runner import _fill_defaults, _render_prompt
from agent.transports.base import ChatResponse

BUILTIN_DIR = Path(__file__).parents[2] / "src" / "agent" / "skills"


def _make_manifest(
    name: str = "test_skill",
    prompt: str = "Processe: {{ input }}",
    tools: list[str] | None = None,
    requires_approval: bool = False,
) -> SkillManifest:
    return SkillManifest(
        name=name,
        description="Skill de teste",
        arguments=[SkillArgument(name="input", type="string", required=True)],
        tools=tools or [],
        requires_approval=requires_approval,
        prompt=prompt,
        content_hash="abc",
    )


def _mock_chat_response(text: str = "resposta mock") -> ChatResponse:
    return ChatResponse(
        text=text,
        tool_calls=[],
        raw={},
        usage={"input_tokens": 10, "output_tokens": 20},
    )


def _mock_transport(text: str = "resposta mock") -> MagicMock:
    t = MagicMock()
    t.chat = AsyncMock(return_value=_mock_chat_response(text))
    return t


class TestRenderPrompt:
    def test_simple_substitution(self) -> None:
        result = _render_prompt("Texto: {{ name }}", {"name": "World"})
        assert result == "Texto: World"

    def test_missing_var_raises(self) -> None:
        with pytest.raises(SkillError, match="ausente"):
            _render_prompt("{{ missing }}", {})

    def test_jinja_conditional(self) -> None:
        tmpl = "{% if fast %}rapido{% else %}devagar{% endif %}"
        assert _render_prompt(tmpl, {"fast": True}) == "rapido"
        assert _render_prompt(tmpl, {"fast": False}) == "devagar"


class TestFillDefaults:
    def test_fills_missing_with_default(self) -> None:
        manifest = _make_manifest()
        manifest.arguments = [
            SkillArgument(name="mode", type="string", default="auto"),
        ]
        filled = _fill_defaults(manifest, {})
        assert filled["mode"] == "auto"

    def test_does_not_override_provided(self) -> None:
        manifest = _make_manifest()
        manifest.arguments = [
            SkillArgument(name="mode", type="string", default="auto"),
        ]
        filled = _fill_defaults(manifest, {"mode": "manual"})
        assert filled["mode"] == "manual"

    def test_none_default_not_filled(self) -> None:
        manifest = _make_manifest()
        manifest.arguments = [SkillArgument(name="opt", type="string")]
        filled = _fill_defaults(manifest, {})
        assert "opt" not in filled


class TestSkillRunnerExecute:
    async def test_simple_skill_returns_llm_text(self) -> None:
        transport = _mock_transport("3 bullets aqui")
        runner = SkillRunner(transport=transport)
        manifest = _make_manifest(prompt="Resume: {{ input }}")
        result = await runner.execute(manifest, {"input": "texto longo"})

        assert result.success is True
        assert result.output == "3 bullets aqui"
        assert result.skill_name == "test_skill"

    async def test_llm_error_raises_skill_error(self) -> None:
        transport = MagicMock()
        transport.chat = AsyncMock(side_effect=RuntimeError("timeout"))
        runner = SkillRunner(transport=transport)
        manifest = _make_manifest()
        with pytest.raises(SkillError, match="LLM falhou"):
            await runner.execute(manifest, {"input": "x"})

    async def test_skill_with_tools_executes_tool_call(self) -> None:
        tool_call = {
            "id": "tc_001",
            "name": "web_search",
            "input": {"query": "python asyncio"},
        }
        first_response = ChatResponse(
            text="",
            tool_calls=[tool_call],
            raw={},
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        second_response = _mock_chat_response("resultado da pesquisa")

        transport = MagicMock()
        transport.chat = AsyncMock(side_effect=[first_response, second_response])

        tool_registry = MagicMock()
        from agent.tools.base import ToolResult
        tool_registry.get = MagicMock(return_value=MagicMock(to_anthropic_schema=MagicMock(
            return_value={"name": "web_search", "description": "busca", "input_schema": {}}
        )))
        tool_registry.execute = AsyncMock(
            return_value=ToolResult(ok=True, output={"results": ["link1"]})
        )

        runner = SkillRunner(transport=transport, tool_registry=tool_registry)
        manifest = _make_manifest(tools=["web_search"])
        result = await runner.execute(manifest, {"input": "python asyncio"})

        assert result.success is True
        assert result.output == "resultado da pesquisa"
        assert transport.chat.call_count == 2
        tool_registry.execute.assert_called_once_with("web_search", {"query": "python asyncio"})

    async def test_failed_tool_call_returns_error_content(self) -> None:
        tool_call = {"id": "tc_002", "name": "web_search", "input": {}}
        first_response = ChatResponse(
            text="", tool_calls=[tool_call], raw={}, usage={"input_tokens": 5, "output_tokens": 5}
        )
        second_response = _mock_chat_response("resposta com erro")

        transport = MagicMock()
        transport.chat = AsyncMock(side_effect=[first_response, second_response])

        tool_registry = MagicMock()
        from agent.tools.base import ToolResult
        tool_registry.get = MagicMock(return_value=MagicMock(
            to_anthropic_schema=MagicMock(return_value={"name": "web_search", "input_schema": {}})
        ))
        tool_registry.execute = AsyncMock(
            return_value=ToolResult(ok=False, error="rate limit")
        )

        runner = SkillRunner(transport=transport, tool_registry=tool_registry)
        manifest = _make_manifest(tools=["web_search"])
        result = await runner.execute(manifest, {"input": "x"})
        # Não deve levantar; LLM recebe o erro e produz uma resposta
        assert result.success is True


class TestManagerRun:
    def _make_manager(self, requires_approval: bool = False) -> tuple[SkillManager, MagicMock]:
        transport = _mock_transport("output da skill")
        manager = SkillManager(skills_dir=Path("/tmp"), transport=transport)
        manifest = _make_manifest(requires_approval=requires_approval)
        from tests.skills.test_manager import _fake_embed
        manager._registry.add(manifest, _fake_embed(manifest.description))
        return manager, transport

    async def test_run_simple_skill(self) -> None:
        manager, _ = self._make_manager()
        result = await manager.run("test_skill", {"input": "hello"})
        assert result.success is True
        assert result.output == "output da skill"

    async def test_run_requires_approval_raises(self) -> None:
        manager, _ = self._make_manager(requires_approval=True)
        with pytest.raises(SkillRequiresApproval, match="test_skill"):
            await manager.run("test_skill", {"input": "x"})

    async def test_run_not_found_raises(self) -> None:
        manager, _ = self._make_manager()
        from agent.skills.schema import SkillNotFound
        with pytest.raises(SkillNotFound):
            await manager.run("nao_existe", {})

    async def test_run_llm_failure_persists_error(self) -> None:
        transport = MagicMock()
        transport.chat = AsyncMock(side_effect=RuntimeError("API down"))
        manager = SkillManager(skills_dir=Path("/tmp"), transport=transport)
        manifest = _make_manifest()
        from tests.skills.test_manager import _fake_embed
        manager._registry.add(manifest, _fake_embed(manifest.description))

        # MemoryStore mock para verificar que invocation é persistida com success=False
        mock_store = MagicMock()
        mock_store.save_skill_invocation = AsyncMock()
        manager._memory_store = mock_store

        with pytest.raises(SkillError):
            await manager.run("test_skill", {"input": "x"}, session_id=uuid4())

        mock_store.save_skill_invocation.assert_called_once()
        record = mock_store.save_skill_invocation.call_args[0][0]
        assert record.success is False
        assert record.error is not None

    async def test_run_persists_success_invocation(self) -> None:
        manager, _ = self._make_manager()
        mock_store = MagicMock()
        mock_store.save_skill_invocation = AsyncMock()
        manager._memory_store = mock_store
        session_id = uuid4()

        await manager.run("test_skill", {"input": "hello"}, session_id=session_id)

        mock_store.save_skill_invocation.assert_called_once()
        record = mock_store.save_skill_invocation.call_args[0][0]
        assert record.success is True
        assert record.session_id == session_id
        assert record.skill_name == "test_skill"
        assert record.latency_ms >= 0
