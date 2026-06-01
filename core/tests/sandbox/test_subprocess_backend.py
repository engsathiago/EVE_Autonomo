"""
Cobre §8 critérios 1, 2, 3, 4 (SubprocessSandbox):
- Classe Sandbox abstrata com SubprocessSandbox implementada.
- Filesystem efêmero entre execuções.
- Timeout mata processo, output truncado.
- Rede: só DENY_ALL suportado.
- Arquivos de input injetados corretamente.
"""

from __future__ import annotations

import pytest

from agent.sandbox.base import NetworkPolicy, SandboxConfig
from agent.sandbox.exceptions import SandboxBackendUnsupported
from agent.sandbox.subprocess_backend import SubprocessSandbox


def _make(wall_time: int = 10, max_output: int = 1_000_000) -> SubprocessSandbox:
    return SubprocessSandbox(
        SandboxConfig(
            wall_time_seconds=wall_time,
            max_output_bytes=max_output,
            network=NetworkPolicy.DENY_ALL,
        )
    )


# ---------------------------------------------------------------------------
# Caso base: echo retorna stdout
# ---------------------------------------------------------------------------


async def test_run_echo_returns_stdout():
    sb = _make()
    result = await sb.run("echo hello")
    await sb.cleanup()
    assert result.exit_code == 0
    assert "hello" in result.stdout


async def test_run_echo_list_command():
    sb = _make()
    result = await sb.run(["echo", "world"])
    await sb.cleanup()
    assert result.exit_code == 0
    assert "world" in result.stdout


# ---------------------------------------------------------------------------
# Timeout mata processo
# ---------------------------------------------------------------------------


async def test_run_timeout_kills_process():
    """sleep 5 com wall_time=1 → timed_out=True (§8 critério 3)."""
    sb = _make(wall_time=1)
    result = await sb.run("sleep 5")
    await sb.cleanup()
    assert result.timed_out is True
    assert result.exit_code != 0  # -1 quando timed_out


async def test_run_timeout_duration_within_margin():
    """Duração não deve ultrapassar wall_time + 3s."""
    sb = _make(wall_time=1)
    result = await sb.run("sleep 10")
    await sb.cleanup()
    assert result.timed_out is True
    assert result.duration_ms < 4_000  # tolerância de 3s


# ---------------------------------------------------------------------------
# Output truncado
# ---------------------------------------------------------------------------


async def test_run_output_truncated():
    """Saída maior que max_output_bytes/2 é truncada (§8 critério 3)."""
    # max_output_bytes=200 → cada lado limitado em 100 bytes
    sb = SubprocessSandbox(
        SandboxConfig(
            wall_time_seconds=10,
            max_output_bytes=200,
            network=NetworkPolicy.DENY_ALL,
        )
    )
    # Gera ~1000 bytes de output
    result = await sb.run("python3 -c \"print('X' * 1000)\"")
    await sb.cleanup()
    assert len(result.stdout) <= 100


# ---------------------------------------------------------------------------
# Filesystem efêmero
# ---------------------------------------------------------------------------


async def test_run_fs_is_ephemeral_between_exec_tool_calls():
    """
    Dois exec_tool consecutivos usam sandboxes distintas.
    Arquivo criado na 1a run não aparece na 2a (§8 critério 4).
    """
    from agent.tools.exec_tool import exec_tool
    from tests.sandbox.conftest import make_subprocess_sandbox

    # 1a execução: cria arquivo em /work (via cwd do subprocess)
    r1 = await exec_tool(
        "python3 -c \"open('marker.txt','w').write('presente')\"",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
    )
    assert r1.exit_code == 0, f"setup falhou: {r1.stderr}"

    # 2a execução: tenta ler o arquivo — deve falhar
    r2 = await exec_tool(
        "python3 -c \"open('marker.txt')\"",
        policy_name="default",
        make_sandbox=make_subprocess_sandbox,
    )
    assert r2.exit_code != 0, "arquivo deveria não existir na 2a execução"


async def test_run_same_instance_creates_fresh_tmpdir():
    """Cada chamada a run() em um mesmo SubprocessSandbox cria tmpdir novo."""
    sb = _make()

    # 1a run: cria arquivo
    r1 = await sb.run("python3 -c \"open('x.txt','w').write('ok')\"")
    assert r1.exit_code == 0

    # 2a run: tenta ler — tmpdir novo, arquivo inexistente
    r2 = await sb.run("python3 -c \"open('x.txt')\"")
    assert r2.exit_code != 0

    await sb.cleanup()


# ---------------------------------------------------------------------------
# Rede: OPEN e ALLOWLIST não suportados
# ---------------------------------------------------------------------------


def test_network_policy_open_raises():
    """SubprocessSandbox rejeita NetworkPolicy.OPEN (§8 critério 3)."""
    with pytest.raises(SandboxBackendUnsupported) as exc_info:
        SubprocessSandbox(SandboxConfig(network=NetworkPolicy.OPEN))
    assert "SubprocessSandbox" in str(exc_info.value) or "DENY_ALL" in str(exc_info.value)


def test_network_policy_allowlist_raises():
    """SubprocessSandbox rejeita NetworkPolicy.ALLOWLIST."""
    with pytest.raises(SandboxBackendUnsupported):
        SubprocessSandbox(SandboxConfig(network=NetworkPolicy.ALLOWLIST))


# ---------------------------------------------------------------------------
# Arquivos de input
# ---------------------------------------------------------------------------


async def test_run_input_files_present():
    """files= injetados são acessíveis pelo processo (§8 critério 2 implícito)."""
    sb = _make()
    result = await sb.run(
        "python3 -c \"print(open('data.txt').read().strip())\"",
        files={"data.txt": b"hello from file"},
    )
    await sb.cleanup()
    assert result.exit_code == 0
    assert "hello from file" in result.stdout


async def test_run_stdin_is_passed():
    """stdin bytes são enviados para o processo."""
    sb = _make()
    result = await sb.run("cat", stdin=b"from stdin\n")
    await sb.cleanup()
    assert result.exit_code == 0
    assert "from stdin" in result.stdout


# ---------------------------------------------------------------------------
# Métricas básicas
# ---------------------------------------------------------------------------


async def test_run_duration_positive():
    sb = _make()
    result = await sb.run("echo ok")
    await sb.cleanup()
    assert result.duration_ms >= 0


async def test_run_exit_code_nonzero():
    sb = _make()
    result = await sb.run(
        "exit 42",
    )
    await sb.cleanup()
    # shell exit code
    assert result.exit_code != 0


async def test_run_stderr_captured():
    sb = _make()
    result = await sb.run("python3 -c \"import sys; sys.stderr.write('err_msg\\n')\"")
    await sb.cleanup()
    assert "err_msg" in result.stderr


async def test_cleanup_is_idempotent():
    """Chamar cleanup() duas vezes não lança exceção."""
    sb = _make()
    await sb.run("echo ok")
    await sb.cleanup()
    await sb.cleanup()  # não deve explodir


# ---------------------------------------------------------------------------
# OOM: documentado como não detectável no subprocess — oom_killed=False sempre
# ---------------------------------------------------------------------------


async def test_oom_killed_always_false_on_subprocess():
    """SubprocessSandbox nunca reporta oom_killed=True (limitação documentada)."""
    sb = _make()
    result = await sb.run("echo ok")
    await sb.cleanup()
    assert result.oom_killed is False
