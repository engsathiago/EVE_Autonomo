"""
Testes de lint — D.1.

Verificam que as regras de encapsulamento do tool router são respeitadas
no source code (L1-L4: grep em arquivos) e que a regressão F8 não ocorreu
(L5: chama Orchestrator.check_step_safety diretamente com strings de código).

Regras verificadas:
  L1: TIER_TOOLS só existe em tiers.py (e possivelmente __init__ como re-export).
  L2: KEYWORD_TOOL_MAP só existe em tool_router.py (e __init__ como re-export).
  L3: context.py NÃO tem lista hardcoded de tools.
  L4: router.py importa resolve_tools_for_step (D.1 ativo).
  L5: F8 regressão — check_step_safety ainda rejeita padrões proibidos.
      Suite completa F8 em tests/sandbox/test_integration_orchestrator.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Raiz do source Python do agente
# __file__ = core/tests/orchestrator/test_lint_d1.py
# parents[2] = core/
SRC = Path(__file__).parents[2] / "src" / "agent"
assert SRC.exists(), f"Diretório src/agent não encontrado em {SRC}"


def _grep(pattern: str, root: Path, exclude_files: list[str] | None = None) -> list[str]:
    """
    Retorna lista de matches no formato 'arquivo:linha:conteúdo'.
    Usa subprocess pra não precisar de dependência extra.
    """
    exclude_files = exclude_files or []
    results = []
    for py_file in sorted(root.rglob("*.py")):
        # Ignora __pycache__
        if "__pycache__" in str(py_file):
            continue
        # Verifica se está na lista de exclusão (por nome de arquivo)
        if py_file.name in exclude_files:
            continue
        try:
            content = py_file.read_text(errors="replace")
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if pattern in line:
                results.append(f"{py_file.relative_to(SRC.parent.parent)}:{i}: {line.strip()}")
    return results


# ─── L1: TIER_TOOLS fora de tiers.py ─────────────────────────────────────────

def test_tier_tools_nao_usado_fora_de_tiers_e_init():
    """
    TIER_TOOLS só pode aparecer em tiers.py (definição shim deprecated)
    e em __init__.py (re-export opcional). Em nenhum outro módulo.
    """
    hits = _grep(
        "TIER_TOOLS",
        root=SRC,
        exclude_files=["tiers.py", "__init__.py"],
    )
    assert not hits, (
        "TIER_TOOLS encontrado fora de tiers.py/__init__.py — viola D.1:\n"
        + "\n".join(f"  {h}" for h in hits)
    )


# ─── L2: KEYWORD_TOOL_MAP fora de tool_router.py ─────────────────────────────

def test_keyword_tool_map_nao_usado_fora_de_tool_router_e_init():
    """
    KEYWORD_TOOL_MAP é privado ao tool_router. Nenhum outro módulo deve
    importar ou referenciar diretamente (quebra encapsulamento do router).
    Re-export em __init__.py é a única exceção (via __all__).
    """
    hits = _grep(
        "KEYWORD_TOOL_MAP",
        root=SRC,
        exclude_files=["tool_router.py", "__init__.py"],
    )
    assert not hits, (
        "KEYWORD_TOOL_MAP encontrado fora de tool_router.py/__init__.py:\n"
        + "\n".join(f"  {h}" for h in hits)
    )


# ─── L3: context.py não tem lista hardcoded ───────────────────────────────────

def test_context_nao_tem_lista_hardcoded_de_tools():
    """
    context.py não deve conter listas hardcoded de tools como
    ["web_search", "read_file", ...].
    A resolução de tools é responsabilidade do tool_router.
    """
    context_file = SRC / "subagents" / "context.py"
    assert context_file.exists(), "context.py não encontrado"

    content = context_file.read_text(errors="replace")

    # Padrões proibidos: lista literal de tool names ou atribuição estática de tools
    forbidden_patterns = [
        '"web_search", "read_file"',
        '"read_file", "web_search"',
        'tools_allowed = ["web_search"',
        'tools_allowed = ["read_file"',
    ]
    violations = []
    for pattern in forbidden_patterns:
        if pattern in content:
            violations.append(f"Padrão proibido encontrado: {pattern!r}")

    assert not violations, (
        "context.py contém lista hardcoded de tools — use tool_router:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ─── L4: router.py importa resolve_tools_for_step ────────────────────────────

def test_router_importa_resolve_tools_for_step():
    """
    D.1 requer que router.py use resolve_tools_for_step em vez de listas estáticas.
    Verifica que o import existe no router.
    """
    router_file = SRC / "orchestrator" / "router.py"
    assert router_file.exists(), "router.py não encontrado"

    content = router_file.read_text(errors="replace")
    assert "resolve_tools_for_step" in content, (
        "router.py não importa resolve_tools_for_step — D.1 pode não estar ativo"
    )


def test_router_nao_tem_lista_hardcoded_de_tools_strategic():
    """
    router.py não deve ter a lista estática de STRATEGIC:
    tools_allowed=["web_search", "read_file", "salvar_memoria", "ler_memoria"]
    que existia antes de D.1.
    """
    router_file = SRC / "orchestrator" / "router.py"
    content = router_file.read_text(errors="replace")

    # A lista estática pré-D.1 era exatamente:
    old_static = 'tools_allowed=["web_search", "read_file", "salvar_memoria", "ler_memoria"]'
    assert old_static not in content.replace(" ", "").replace("\n", ""), (
        "router.py ainda contém lista estática de STRATEGIC — D.1 não foi aplicado"
    )


# ─── L5: F8 regressão — check_step_safety ainda rejeita padrões proibidos ────
#
# O gate F8 é sobre CÓDIGO DINÂMICO (strings de step), não sobre arquivos estáticos.
# A função Orchestrator.check_step_safety() faz esse check. D.1 não deve ter
# regredido essa função. Testamos os padrões mais críticos diretamente.
# A suite completa do F8 está em tests/sandbox/test_integration_orchestrator.py.

def _make_orchestrator():
    """Orchestrator mínimo para testar check_step_safety sem Postgres/Redis."""
    from unittest.mock import MagicMock
    from agent.orchestrator.router import Orchestrator
    from agent.orchestrator.tiers import TierClassifier

    return Orchestrator(
        model_router=MagicMock(),
        task_store=MagicMock(),
        subagent_pool=MagicMock(),
        classifier=MagicMock(spec=TierClassifier),
    )


def test_f8_check_step_safety_nao_regrediu_subprocess():
    """F8 regressão: check_step_safety ainda rejeita subprocess.run."""
    orch = _make_orchestrator()
    violations = orch.check_step_safety("import subprocess; subprocess.run(['ls'])")
    assert len(violations) >= 1
    assert any("subprocess" in v for v in violations)


def test_f8_check_step_safety_nao_regrediu_os_system():
    """F8 regressão: check_step_safety ainda rejeita os.system."""
    orch = _make_orchestrator()
    violations = orch.check_step_safety("import os; os.system('rm -rf /')")
    assert len(violations) >= 1
    assert any("os.system" in v for v in violations)


def test_f8_check_step_safety_aceita_exec_tool():
    """F8 regressão: exec_tool legítimo não é bloqueado."""
    orch = _make_orchestrator()
    code = "from agent.tools.exec_tool import exec_tool\nresult = await exec_tool('echo ok')"
    violations = orch.check_step_safety(code)
    assert violations == [], f"exec_tool legítimo foi bloqueado: {violations}"


def test_f8_check_step_safety_existe_no_orchestrator():
    """D.1 não removeu check_step_safety do Orchestrator."""
    from agent.orchestrator.router import Orchestrator
    assert hasattr(Orchestrator, "check_step_safety"), (
        "Orchestrator.check_step_safety removido — regressão F8"
    )
