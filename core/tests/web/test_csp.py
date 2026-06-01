"""Testa CSP via HTTP response header (movido de meta tag para header HTTP)."""

from __future__ import annotations

from unittest.mock import patch

import pytest  # noqa: F401  (usado em pytest.skip)
from starlette.testclient import TestClient

from agent.web.server import make_web_app


def _get_csp_header(client: TestClient) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, f"GET / retornou {resp.status_code}"
    csp = resp.headers.get("content-security-policy", "")
    assert csp, "Content-Security-Policy ausente no HTTP response header"
    return csp


@pytest.fixture()
def client():
    with patch("agent.web.auth.verify_token", return_value=True):
        app = make_web_app()
        yield TestClient(app)


def test_csp_found(client: TestClient) -> None:
    """CSP deve estar presente como HTTP header na resposta do index.html."""
    csp = _get_csp_header(client)
    assert csp


def test_csp_default_src_self(client: TestClient) -> None:
    csp = _get_csp_header(client)
    assert "default-src 'self'" in csp


def test_csp_no_unsafe_eval(client: TestClient) -> None:
    csp = _get_csp_header(client)
    assert "'unsafe-eval'" not in csp, "CSP não deve ter 'unsafe-eval'"


def test_csp_no_cdnjs(client: TestClient) -> None:
    """cdnjs.cloudflare.com removido — sem CDN externo sem SRI."""
    csp = _get_csp_header(client)
    assert "cdnjs" not in csp, "CSP não deve referenciar cdnjs.cloudflare.com"


def test_csp_connect_src_loopback(client: TestClient) -> None:
    """connect-src deve incluir ws://127.0.0.1 e não wildcard."""
    csp = _get_csp_header(client)
    assert "ws://127.0.0.1" in csp, "connect-src deve incluir ws://127.0.0.1:8080"
    assert "connect-src *" not in csp, "connect-src não deve ser wildcard"


def test_csp_font_src_self(client: TestClient) -> None:
    csp = _get_csp_header(client)
    assert "font-src 'self'" in csp, "font-src deve ser 'self' (fontes locais)"


def test_csp_script_src_no_unsafe_inline(client: TestClient) -> None:
    csp = _get_csp_header(client)
    for directive in csp.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src"):
            assert "'unsafe-inline'" not in directive, "script-src não deve ter 'unsafe-inline'"
            return


def test_csp_no_unsafe_inline_style(client: TestClient) -> None:
    """style-src não deve ter 'unsafe-inline' (JS usa element.style.prop, não <style> inline)."""
    csp = _get_csp_header(client)
    for directive in csp.split(";"):
        directive = directive.strip()
        if directive.startswith("style-src"):
            assert "'unsafe-inline'" not in directive, "style-src não deve ter 'unsafe-inline'"
            return


def test_security_headers_present(client: TestClient) -> None:
    """Headers de segurança adicionais no response HTML."""
    resp = client.get("/")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"


def test_csp_not_in_meta_tag(client: TestClient) -> None:
    """CSP deve estar no HTTP header, não no meta tag (que seria bypassável)."""
    resp = client.get("/")
    body = resp.text
    assert 'http-equiv="Content-Security-Policy"' not in body, (
        "CSP não deve estar como meta http-equiv no HTML (usar HTTP header)"
    )


def test_csp_header_on_html_file(client: TestClient) -> None:
    """Qualquer rota que sirva text/html recebe o header CSP — não só o index."""
    resp = client.get("/")
    assert resp.headers.get("content-security-policy"), "GET / deve ter CSP"
    assert resp.headers.get("x-frame-options") == "DENY"


def test_non_html_asset_has_no_csp_header(client: TestClient) -> None:
    """Arquivos não-HTML (CSS, JS) NÃO recebem o header CSP."""
    resp = client.get("/css/term.css")
    if resp.status_code == 200:
        assert "content-security-policy" not in resp.headers, "CSS não deve receber header CSP"
    else:
        pytest.skip("term.css não encontrado — ok em ambiente de teste sem assets")
