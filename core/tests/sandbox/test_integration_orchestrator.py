"""
Cobre §8 critério 2: Orchestrator.check_step_safety rejeita padrões proibidos
(subprocess, os.system, eval, exec builtin) e aceita exec_tool.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixture mínima do Orchestrator sem dependências de Postgres/Redis
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator():
    """Instância de Orchestrator com mocks mínimos para testar check_step_safety."""
    from unittest.mock import MagicMock
    from agent.orchestrator.router import Orchestrator
    from agent.orchestrator.tiers import TierClassifier

    mock_router = MagicMock()
    mock_store = MagicMock()
    mock_pool = MagicMock()
    mock_classifier = MagicMock(spec=TierClassifier)

    return Orchestrator(
        model_router=mock_router,
        task_store=mock_store,
        subagent_pool=mock_pool,
        classifier=mock_classifier,
    )


# ---------------------------------------------------------------------------
# Padrões proibidos
# ---------------------------------------------------------------------------

def test_check_step_safety_rejects_subprocess_run(orchestrator):
    code = "import subprocess; subprocess.run(['ls'])"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1
    assert any("subprocess.run" in v for v in violations)


def test_check_step_safety_rejects_subprocess_popen(orchestrator):
    code = "import subprocess; p = subprocess.Popen(['ls'])"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1
    assert any("subprocess.Popen" in v for v in violations)


def test_check_step_safety_rejects_subprocess_call(orchestrator):
    code = "subprocess.call(['echo', 'hi'])"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1


def test_check_step_safety_rejects_subprocess_check_output(orchestrator):
    code = "result = subprocess.check_output(['ls', '-la'])"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1


def test_check_step_safety_rejects_os_system(orchestrator):
    code = "import os; os.system('rm -rf /')"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1
    assert any("os.system" in v for v in violations)


def test_check_step_safety_rejects_eval(orchestrator):
    code = "result = eval('1+1')"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1
    assert any("eval" in v for v in violations)


def test_check_step_safety_rejects_exec_builtin(orchestrator):
    code = "exec('print(\"hello\")')"
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 1
    assert any("exec" in v for v in violations)


# ---------------------------------------------------------------------------
# Código legítimo — sem violações
# ---------------------------------------------------------------------------

def test_check_step_safety_accepts_exec_tool(orchestrator):
    code = "from agent.tools.exec_tool import exec_tool\nresult = await exec_tool('echo ok')"
    violations = orchestrator.check_step_safety(code)
    assert violations == []


def test_check_step_safety_accepts_clean_code(orchestrator):
    code = """
import json
data = json.loads('{"key": "value"}')
print(data["key"])
"""
    violations = orchestrator.check_step_safety(code)
    assert violations == []


def test_check_step_safety_empty_string(orchestrator):
    violations = orchestrator.check_step_safety("")
    assert violations == []


def test_check_step_safety_violation_message_mentions_exec_tool(orchestrator):
    """Mensagem de violação deve orientar o dev a usar exec_tool."""
    violations = orchestrator.check_step_safety("subprocess.run(['ls'])")
    assert any("exec_tool" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# Múltiplas violações no mesmo código
# ---------------------------------------------------------------------------

def test_check_step_safety_multiple_violations(orchestrator):
    code = """
subprocess.run(['ls'])
os.system('echo hi')
eval('dangerous')
"""
    violations = orchestrator.check_step_safety(code)
    assert len(violations) >= 3
