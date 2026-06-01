"""
Teste de integração end-to-end com transport mockado.
Verifica que o agente completa uma tarefa simples usando filesystem tool.
"""
import pytest

from agent.core import AIAgent
from agent.tools.registry import ToolRegistry
from agent.transports.base import ChatResponse
from tests.test_core import MockTransport


@pytest.mark.asyncio
async def test_agent_reads_file_and_reports(tmp_path, monkeypatch):
    """Agente deve ler um arquivo e retornar o conteúdo."""
    # Configura workspace para apontar para tmp_path
    monkeypatch.setattr(
        "agent.tools.builtin.filesystem.get_settings",
        lambda: type("S", (), {
            "agent": type("A", (), {"workspace_paths": [str(tmp_path)]})()
        })(),
    )

    target = tmp_path / "info.txt"
    target.write_text("o segredo é 42")

    from agent.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool
    from agent.tools.builtin.shell import ShellTool
    from agent.tools.builtin.web_search import WebSearchTool

    registry = ToolRegistry()
    for t in [ReadFileTool(), WriteFileTool(), ListDirTool(), ShellTool(), WebSearchTool()]:
        registry.register(t)

    # Transport: 1ª chamada usa read_file, 2ª finaliza
    tool_call = {
        "id": "tc_read",
        "name": "read_file",
        "input": {"path": str(target)},
    }
    responses = [
        ChatResponse(
            text="Vou ler o arquivo.",
            tool_calls=[tool_call],
            raw={},
            usage={"input_tokens": 20, "output_tokens": 10},
        ),
        ChatResponse(
            text="O conteúdo é: o segredo é 42",
            tool_calls=[],
            raw={},
            usage={"input_tokens": 30, "output_tokens": 15},
        ),
    ]

    agent = AIAgent(
        transport=MockTransport(responses),
        tool_registry=registry,
    )
    result = await agent.run(f"leia o arquivo {target} e me diga o conteúdo")

    assert result.iterations == 2
    assert "42" in result.final_text
    assert result.total_input_tokens == 50
    assert result.total_output_tokens == 25


@pytest.mark.asyncio
async def test_agent_handles_tool_error_gracefully(tmp_path, monkeypatch):
    """Agente deve continuar operando quando uma tool falha."""
    monkeypatch.setattr(
        "agent.tools.builtin.filesystem.get_settings",
        lambda: type("S", (), {
            "agent": type("A", (), {"workspace_paths": [str(tmp_path)]})()
        })(),
    )

    from agent.tools.builtin.filesystem import ReadFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())

    # Tool call para arquivo que não existe
    tool_call = {
        "id": "tc_err",
        "name": "read_file",
        "input": {"path": str(tmp_path / "ghost.txt")},
    }
    responses = [
        ChatResponse(
            text="Vou tentar ler.",
            tool_calls=[tool_call],
            raw={},
            usage={"input_tokens": 10, "output_tokens": 5},
        ),
        ChatResponse(
            text="O arquivo não existe.",
            tool_calls=[],
            raw={},
            usage={"input_tokens": 15, "output_tokens": 8},
        ),
    ]

    agent = AIAgent(transport=MockTransport(responses), tool_registry=registry)
    result = await agent.run("leia ghost.txt")

    # Deve completar sem exceção, mesmo com tool error
    assert result.iterations == 2
    assert result.final_text != ""
