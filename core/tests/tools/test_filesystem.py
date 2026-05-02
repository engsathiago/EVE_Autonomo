import pytest

from agent.tools.builtin.filesystem import ListDirTool, ReadFileTool, WriteFileTool


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Configura tmp_path como workspace permitido."""
    monkeypatch.setattr(
        "agent.tools.builtin.filesystem.get_settings",
        lambda: type("S", (), {
            "agent": type("A", (), {"workspace_paths": [str(tmp_path)]})()
        })(),
    )
    return tmp_path


# ── ReadFileTool ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_file_ok(tmp_workspace):
    f = tmp_workspace / "hello.txt"
    f.write_text("olá mundo")
    result = await ReadFileTool().execute(path=str(f))
    assert result.ok
    assert result.output == "olá mundo"


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_workspace):
    result = await ReadFileTool().execute(path=str(tmp_workspace / "nope.txt"))
    assert not result.ok
    assert "não encontrado" in result.error


@pytest.mark.asyncio
async def test_read_file_outside_workspace(tmp_workspace):
    result = await ReadFileTool().execute(path="/etc/passwd")
    assert not result.ok
    assert "path_outside_workspace" in result.error


@pytest.mark.asyncio
async def test_read_file_too_large(tmp_workspace, monkeypatch):
    monkeypatch.setattr("agent.tools.builtin.filesystem._READ_LIMIT", 5)
    f = tmp_workspace / "big.txt"
    f.write_text("abcdefghij")
    result = await ReadFileTool().execute(path=str(f))
    assert not result.ok
    assert "file_too_large" in result.error


# ── WriteFileTool ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_file_creates_file(tmp_workspace):
    target = tmp_workspace / "new.txt"
    result = await WriteFileTool().execute(path=str(target), content="conteúdo")
    assert result.ok
    assert target.read_text() == "conteúdo"


@pytest.mark.asyncio
async def test_write_file_append(tmp_workspace):
    target = tmp_workspace / "append.txt"
    target.write_text("linha1\n")
    result = await WriteFileTool().execute(path=str(target), content="linha2\n", mode="append")
    assert result.ok
    assert target.read_text() == "linha1\nlinha2\n"


@pytest.mark.asyncio
async def test_write_file_creates_parents(tmp_workspace):
    target = tmp_workspace / "sub" / "dir" / "file.txt"
    result = await WriteFileTool().execute(path=str(target), content="x")
    assert result.ok
    assert target.exists()


@pytest.mark.asyncio
async def test_write_file_outside_workspace(tmp_workspace):
    result = await WriteFileTool().execute(path="/tmp/evil.txt", content="x")
    assert not result.ok


# ── ListDirTool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_dir_ok(tmp_workspace):
    (tmp_workspace / "a.txt").write_text("a")
    (tmp_workspace / "b.txt").write_text("b")
    result = await ListDirTool().execute(path=str(tmp_workspace))
    assert result.ok
    names = [e["path"].split("/")[-1] for e in result.output]
    assert "a.txt" in names
    assert "b.txt" in names


@pytest.mark.asyncio
async def test_list_dir_not_found(tmp_workspace):
    result = await ListDirTool().execute(path=str(tmp_workspace / "ghost"))
    assert not result.ok


@pytest.mark.asyncio
async def test_list_dir_recursive(tmp_workspace):
    sub = tmp_workspace / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("deep")
    result = await ListDirTool().execute(path=str(tmp_workspace), recursive=True)
    assert result.ok
    paths = [e["path"] for e in result.output]
    assert any("deep.txt" in p for p in paths)
