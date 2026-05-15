"""Testa CSP no HTML servido pelo backend."""
from __future__ import annotations

import re
from pathlib import Path

_HTML_FILE = Path(__file__).parent.parent.parent.parent / "webui" / "public" / "index.html"


def _get_csp_value() -> str:
    content = _HTML_FILE.read_text()
    # Extrai o bloco <meta ... Content-Security-Policy ... content="...">
    # O valor do content usa aspas duplas externas e aspas simples internamente
    meta_block_match = re.search(
        r'<meta[^>]+Content-Security-Policy[^>]+>',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not meta_block_match:
        raise ValueError("CSP meta tag não encontrada no index.html")
    meta_block = meta_block_match.group(0)
    # Extrai o valor entre content="..." (aspas duplas, valor pode ter aspas simples)
    val_match = re.search(r'content="([^"]+)"', meta_block, re.DOTALL)
    if val_match:
        return val_match.group(1)
    raise ValueError("Atributo content não encontrado na meta tag CSP")


def test_csp_found() -> None:
    """CSP deve estar presente no index.html."""
    csp = _get_csp_value()
    assert csp, "CSP vazio"


def test_csp_default_src_self() -> None:
    csp = _get_csp_value()
    assert "default-src 'self'" in csp


def test_csp_no_unsafe_eval() -> None:
    csp = _get_csp_value()
    assert "'unsafe-eval'" not in csp, "CSP não deve ter 'unsafe-eval'"


def test_csp_connect_src_loopback() -> None:
    """connect-src deve incluir ws://127.0.0.1 e não wildcard."""
    csp = _get_csp_value()
    assert "ws://127.0.0.1" in csp, "connect-src deve incluir ws://127.0.0.1:8080"
    assert "connect-src *" not in csp, "connect-src não deve ser wildcard"


def test_csp_font_src_self() -> None:
    csp = _get_csp_value()
    assert "font-src 'self'" in csp, "font-src deve ser 'self' (fontes locais)"


def test_csp_script_src_no_unsafe_inline() -> None:
    csp = _get_csp_value()
    # Extrai diretiva script-src
    for directive in csp.replace("\n", " ").split(";"):
        directive = directive.strip()
        if directive.startswith("script-src"):
            assert "'unsafe-inline'" not in directive, (
                "script-src não deve ter 'unsafe-inline'"
            )
            return
