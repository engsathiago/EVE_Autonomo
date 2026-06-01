"""E2E smoke test com Playwright headless (C4).

Skip se playwright não instalado — NÃO falha o suite por ausência da lib.
Requer: `agent web start` rodando em 127.0.0.1:8080 e variável AGENT_WEB_TOKEN.
"""

from __future__ import annotations

import os

import pytest

# Skip completo se playwright não estiver instalado
playwright = pytest.importorskip("playwright.sync_api", reason="playwright não instalado — skip E2E")


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    token = os.getenv("AGENT_WEB_TOKEN")
    if not token:
        pytest.skip("AGENT_WEB_TOKEN não definido — skip smoke E2E")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        yield page, token
        browser.close()


def test_index_loads(browser_page) -> None:
    page, token = browser_page
    page.goto(f"http://127.0.0.1:8080/?token={token}")
    page.wait_for_selector("#app:not(.hidden)", timeout=10000)
    assert "Agent Dashboard" in page.title()


def test_8_panels_visible(browser_page) -> None:
    page, token = browser_page
    page.goto(f"http://127.0.0.1:8080/?token={token}")
    page.wait_for_selector("#app:not(.hidden)", timeout=10000)

    panel_ids = [
        "#panel-chat",
        "#panel-missions",
        "#panel-skills",
        "#panel-memory",
        "#panel-traces",
        "#panel-critic",
        "#panel-subagents",
        "#panel-approvals",
    ]
    for panel_id in panel_ids:
        assert page.is_visible(panel_id), f"Painel {panel_id} não visível"


def test_metrics_bar_loads(browser_page) -> None:
    page, token = browser_page
    page.goto(f"http://127.0.0.1:8080/?token={token}")
    page.wait_for_selector(".metrics-bar", timeout=10000)
    assert page.is_visible(".metrics-bar")


def test_no_console_errors(browser_page) -> None:
    page, _ = browser_page
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.wait_for_timeout(2000)
    # Permite alguns erros de rede (sem DB) mas não erros JS
    js_errors = [e for e in errors if "SyntaxError" in e or "ReferenceError" in e or "TypeError" in e]
    assert not js_errors, f"Erros JavaScript: {js_errors}"
