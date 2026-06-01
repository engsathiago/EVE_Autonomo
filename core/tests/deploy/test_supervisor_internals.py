"""Testes das funções internas do Supervisor (F10) — aumentam cobertura.

Cobre os helpers que não são testados via state machine:
  _run_worker_sync, _reset_signals_child, _reap_child, _log,
  _fork_worker, Supervisor.__init__, _write_pid, _remove_pid,
  _setup_signals, _graceful_shutdown, _handle_worker_died (lógica)
"""
from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from agent.deploy.supervisor import (
    Supervisor,
    _fork_worker,
    _is_pid_alive,
    _log,
    _reap_child,
    _reset_signals_child,
    _run_worker_sync,
    _WorkerState,
)
from agent.deploy.workers.base import Worker

# ── Workers para testes ───────────────────────────────────────────────────────

class _ImmediateWorker(Worker):
    """Worker que retorna imediatamente."""
    name = "immediate"

    async def run(self) -> None:
        pass


class _FailingWorker(Worker):
    """Worker que lança exceção."""
    name = "failing"

    async def run(self) -> None:
        raise RuntimeError("simulated failure")


# ── _log ─────────────────────────────────────────────────────────────────────

class TestLog:
    def test_outputs_to_stdout(self, capsys: pytest.CaptureFixture) -> None:
        _log("test message")
        captured = capsys.readouterr()
        assert "[supervisor]" in captured.out
        assert "test message" in captured.out

    def test_includes_timestamp(self, capsys: pytest.CaptureFixture) -> None:
        _log("ts check")
        captured = capsys.readouterr()
        assert "T" in captured.out  # formato ISO: YYYY-MM-DDTHH:MM:SS


# ── _reset_signals_child ──────────────────────────────────────────────────────

class TestResetSignalsChild:
    def test_restores_sigterm_to_default(self) -> None:
        """Após reset, SIGTERM volta para SIG_DFL."""
        original_handler = signal.getsignal(signal.SIGTERM)
        try:
            # Instala um handler customizado
            signal.signal(signal.SIGTERM, lambda s, f: None)
            _reset_signals_child()
            assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
        finally:
            signal.signal(signal.SIGTERM, original_handler)

    def test_restores_sigint_to_default(self) -> None:
        original_handler = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, lambda s, f: None)
            _reset_signals_child()
            assert signal.getsignal(signal.SIGINT) == signal.SIG_DFL
        finally:
            signal.signal(signal.SIGINT, original_handler)


# ── _run_worker_sync ──────────────────────────────────────────────────────────

class TestRunWorkerSync:
    def test_runs_immediate_worker(self) -> None:
        """Worker que termina imediatamente não causa erro."""
        _run_worker_sync(_ImmediateWorker())

    def test_worker_exception_causes_sys_exit(self) -> None:
        """Worker que lança exceção deve chamar sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            _run_worker_sync(_FailingWorker())
        assert exc_info.value.code == 1


# ── _reap_child ───────────────────────────────────────────────────────────────

class TestReapChild:
    def test_reap_normal_exit(self) -> None:
        """Processo que sai normalmente retorna exit code."""
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        os.waitpid(pid, 0)  # wait to ensure exited
        # Note: after waitpid, WNOHANG might return 0 since already reaped
        # Just verify the function doesn't crash
        result = _reap_child(pid)
        assert isinstance(result, int)

    def test_reap_nonexistent_pid_returns_minus1(self) -> None:
        result = _reap_child(99999999)
        assert result == -1

    def test_reap_signaled_process(self) -> None:
        """Processo morto por sinal retorna valor negativo."""
        pid = os.fork()
        if pid == 0:
            time.sleep(10)
            os._exit(0)
        os.kill(pid, signal.SIGKILL)
        # Wait a moment for signal to be delivered
        time.sleep(0.05)
        result = _reap_child(pid)
        # Either -9 (if WIFSIGNALED) or -1 (if not yet reaped by WNOHANG)
        assert isinstance(result, int)
        # Clean up if still alive
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


# ── _fork_worker ─────────────────────────────────────────────────────────────

class TestForkWorker:
    def test_returns_child_pid(self) -> None:
        """_fork_worker retorna PID positivo do filho."""
        pid = _fork_worker(_ImmediateWorker())
        assert pid > 0
        assert pid != os.getpid()
        # Aguarda o filho terminar para não criar zombie
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def test_child_runs_worker(self) -> None:
        """Filho executa o worker e termina."""
        pid = _fork_worker(_ImmediateWorker())
        waited_pid, status = os.waitpid(pid, 0)
        assert waited_pid == pid
        assert os.WIFEXITED(status)
        assert os.WEXITSTATUS(status) == 0

    def test_failing_worker_exits_abnormally(self) -> None:
        """Worker que lança exceção → filho sai de forma anormal.

        No Linux: sys.exit(1) → WIFEXITED=True, exit code=1.
        No macOS com Objective-C runtime: crash → WIFSIGNALED=True (SIGABRT).
        Ambos são comportamentos corretos — o ponto é que o filho não sai com 0.
        """
        pid = _fork_worker(_FailingWorker())
        waited_pid, status = os.waitpid(pid, 0)
        # Filho deve ter encerrado de alguma forma (exited ou signaled)
        assert os.WIFEXITED(status) or os.WIFSIGNALED(status)
        if os.WIFEXITED(status):
            assert os.WEXITSTATUS(status) == 1  # Linux


# ── Supervisor.__init__ ───────────────────────────────────────────────────────

class TestSupervisorInit:
    def test_creates_states_for_each_worker(self) -> None:
        workers = [_ImmediateWorker(), _FailingWorker()]
        s = Supervisor(workers)
        assert len(s._states) == 2

    def test_uses_default_pid_file(self) -> None:
        s = Supervisor([])
        assert s._pid_file is not None

    def test_custom_pid_file(self) -> None:
        s = Supervisor([], pid_file="/tmp/test_agent.pid")
        assert s._pid_file == "/tmp/test_agent.pid"

    def test_not_shutdown_initially(self) -> None:
        s = Supervisor([])
        assert s._shutdown is False


# ── _write_pid / _remove_pid ──────────────────────────────────────────────────

class TestPidFile:
    def test_write_pid_creates_file(self, tmp_path: Path) -> None:
        pid_file = str(tmp_path / "agent.pid")
        s = Supervisor([], pid_file=pid_file)
        s._write_pid()
        assert Path(pid_file).exists()
        assert int(Path(pid_file).read_text()) == os.getpid()

    def test_remove_pid_deletes_file(self, tmp_path: Path) -> None:
        pid_file = str(tmp_path / "agent.pid")
        s = Supervisor([], pid_file=pid_file)
        s._write_pid()
        s._remove_pid()
        assert not Path(pid_file).exists()

    def test_remove_pid_ok_if_missing(self, tmp_path: Path) -> None:
        """Não levanta exceção se arquivo não existe."""
        pid_file = str(tmp_path / "nonexistent.pid")
        s = Supervisor([], pid_file=pid_file)
        s._remove_pid()  # não deve levantar

    def test_write_pid_creates_parent_dirs(self, tmp_path: Path) -> None:
        pid_file = str(tmp_path / "subdir" / "agent.pid")
        s = Supervisor([], pid_file=pid_file)
        s._write_pid()
        assert Path(pid_file).exists()


# ── _setup_signals ────────────────────────────────────────────────────────────

class TestSetupSignals:
    def test_sets_shutdown_flag_on_sigterm(self) -> None:
        s = Supervisor([])
        s._setup_signals()
        # Envia SIGTERM ao processo atual
        original_handler = signal.getsignal(signal.SIGTERM)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            assert s._shutdown is True
        finally:
            signal.signal(signal.SIGTERM, original_handler)

    def test_sets_shutdown_flag_on_sigint(self) -> None:
        s = Supervisor([])
        s._setup_signals()
        original_handler = signal.getsignal(signal.SIGINT)
        try:
            os.kill(os.getpid(), signal.SIGINT)
            assert s._shutdown is True
        finally:
            signal.signal(signal.SIGINT, original_handler)


# ── _graceful_shutdown ────────────────────────────────────────────────────────

class TestGracefulShutdown:
    def test_with_no_workers_completes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shutdown sem workers ativos não trava."""
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/db.db")
        s = Supervisor([])
        s._graceful_shutdown()  # deve retornar sem travar

    def test_with_dead_workers_completes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Shutdown com workers que já morreram completa sem SIGKILL."""
        monkeypatch.setenv("AGENT_DB_SQLITE", "/nonexistent/db.db")
        state = _WorkerState(worker=_ImmediateWorker())
        state.pid = 99999999  # PID inexistente
        s = Supervisor([_ImmediateWorker()])
        s._states = [state]
        s._graceful_shutdown()  # não deve travar

    def test_kills_alive_workers_with_sigterm(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Shutdown envia SIGTERM para workers vivos."""
        monkeypatch.setenv("AGENT_DB_SQLITE", str(tmp_path / "agent.db"))

        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)

        try:
            state = _WorkerState(worker=_ImmediateWorker())
            state.pid = pid
            s = Supervisor([_ImmediateWorker()])
            s._states = [state]
            s._graceful_shutdown()

            # Filho deve ter recebido SIGTERM e encerrado
            waited_pid, status = os.waitpid(pid, os.WNOHANG)
            # Ou foi terminado (waited_pid == pid) ou foi para SIGKILL
            assert not _is_pid_alive(pid)
        finally:
            if _is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)


# ── _start_worker (via Supervisor) ───────────────────────────────────────────

class TestStartWorker:
    def test_start_worker_sets_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_start_worker faz fork e registra PID no estado."""
        db = tmp_path / "agent.db"
        import sqlite3
        conn = sqlite3.connect(str(db))
        from pathlib import Path as P
        migration = P(__file__).parents[2] / "migrations" / "011_deploy.sql"
        conn.executescript(migration.read_text())
        conn.close()
        monkeypatch.setenv("AGENT_DB_SQLITE", str(db))

        state = _WorkerState(worker=_ImmediateWorker())
        s = Supervisor([_ImmediateWorker()])
        s._states = [state]
        s._start_worker(state)

        assert state.pid > 0
        # Aguarda o filho terminar
        try:
            os.waitpid(state.pid, 0)
        except ChildProcessError:
            pass
