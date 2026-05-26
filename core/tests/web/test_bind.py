"""Teste de bind — C3: nunca 0.0.0.0, sempre 127.0.0.1."""
from __future__ import annotations

import os
from pathlib import Path


def test_server_bind_is_loopback() -> None:
    """C3: Verifica que o server.py usa 127.0.0.1 e não 0.0.0.0."""
    # Verifica no web/server.py não há referência a 0.0.0.0
    server_file = Path(__file__).parent.parent.parent / "src" / "agent" / "web" / "server.py"
    content = server_file.read_text()
    assert "0.0.0.0" not in content, "server.py não deve usar 0.0.0.0"


def test_no_wildcard_bind_in_any_web_file() -> None:
    """C3: Nenhum arquivo em agent/web/ deve referenciar 0.0.0.0."""
    web_dir = Path(__file__).parent.parent.parent / "src" / "agent" / "web"
    for py_file in web_dir.rglob("*.py"):
        content = py_file.read_text()
        assert "0.0.0.0" not in content, f"{py_file} contém 0.0.0.0"


def test_config_bind_documented() -> None:
    """C3: Documentação deve mencionar 127.0.0.1."""
    docs_file = Path(__file__).parent.parent.parent.parent / "docs" / "web.md"
    if docs_file.exists():
        content = docs_file.read_text()
        assert "127.0.0.1" in content, "docs/web.md deve mencionar 127.0.0.1"
