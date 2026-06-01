"""C7: Zero innerHTML em conteúdo dinâmico no frontend."""
from __future__ import annotations

import re
from pathlib import Path

_JS_DIR = Path(__file__).parent.parent.parent.parent / "webui" / "public" / "js"

# Padrão que captura atribuições dinâmicas de innerHTML
# Ignora linhas que são comentários (// ... ou /* ... */)
_INNERHTML_PATTERN = re.compile(r'\.innerHTML\s*=')
_COMMENT_LINE_PATTERN = re.compile(r'^\s*//')


def _is_comment_line(line: str) -> bool:
    return bool(_COMMENT_LINE_PATTERN.match(line))


def test_no_innerhtml_dynamic_assignment() -> None:
    """C7: Nenhum arquivo JS deve usar .innerHTML = em conteúdo dinâmico."""
    violations: list[str] = []

    for js_file in sorted(_JS_DIR.rglob("*.js")):
        lines = js_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, start=1):
            if _is_comment_line(line):
                continue
            if _INNERHTML_PATTERN.search(line):
                violations.append(f"{js_file.relative_to(_JS_DIR.parent.parent)}:{i}: {line.strip()}")

    assert not violations, (
        "Encontrado .innerHTML em conteúdo dinâmico (use textContent ou createElement):\n"
        + "\n".join(violations)
    )


def test_no_eval_in_js() -> None:
    """Sem eval() no frontend (C7 complementar)."""
    violations: list[str] = []
    pattern = re.compile(r'\beval\s*\(')

    for js_file in sorted(_JS_DIR.rglob("*.js")):
        lines = js_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, start=1):
            if _is_comment_line(line):
                continue
            if pattern.search(line):
                violations.append(f"{js_file}:{i}: {line.strip()}")

    assert not violations, "Encontrado eval() no frontend:\n" + "\n".join(violations)
