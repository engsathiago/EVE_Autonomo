import pytest

from agent.tools.builtin.shell import ShellTool


@pytest.mark.asyncio
async def test_shell_echo():
    result = await ShellTool().execute(command="echo hello")
    assert result.ok
    assert "hello" in result.output["stdout"]


@pytest.mark.asyncio
async def test_shell_returncode_nonzero():
    result = await ShellTool().execute(command="exit 1")
    assert not result.ok
    assert result.output["returncode"] == 1


@pytest.mark.asyncio
async def test_shell_captures_stderr():
    result = await ShellTool().execute(command="echo errormsg >&2; exit 1")
    assert "errormsg" in result.output["stderr"]


@pytest.mark.asyncio
async def test_shell_blacklist_blocks(monkeypatch):
    monkeypatch.setattr(
        "agent.tools.builtin.shell.get_settings",
        lambda: type("S", (), {
            "agent": type("A", (), {"shell_blacklist": [r"rm\s+-rf\s+/"]})()
        })(),
    )
    result = await ShellTool().execute(command="rm -rf /tmp/test")
    assert not result.ok
    assert "bloqueado" in result.error


@pytest.mark.asyncio
async def test_shell_timeout(monkeypatch):
    result = await ShellTool().execute(command="sleep 10", timeout=1)
    assert not result.ok
    assert "Timeout" in result.error


@pytest.mark.asyncio
async def test_shell_duration_tracked():
    result = await ShellTool().execute(command="echo ok")
    assert result.ok
    assert result.output["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_shell_truncates_large_output(monkeypatch):
    monkeypatch.setattr("agent.tools.builtin.shell._OUTPUT_LIMIT", 10)
    result = await ShellTool().execute(command="python3 -c \"print('a' * 100)\"")
    assert result.ok
    assert "truncado" in result.output["stdout"]
