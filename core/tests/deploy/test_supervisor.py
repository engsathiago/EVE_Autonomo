"""Testes do Supervisor (F10).

Cobre flapping detection, backoff, _WorkerState e helpers.
Não usa os.fork() — testa a lógica de state machine diretamente.
"""
from __future__ import annotations

import os
import time
from collections import deque

import pytest

from agent.deploy.supervisor import (
    _BACKOFF_SEQUENCE,
    _FLAPPING_MAX_RESTARTS,
    _FLAPPING_WINDOW_S,
    _WorkerState,
    _is_pid_alive,
    _sd_notify,
)
from agent.deploy.workers.base import Worker


class _FakeWorker(Worker):
    name = "fake"

    async def run(self) -> None:
        pass


# ── WorkerState ───────────────────────────────────────────────────────────────

class TestWorkerState:
    def test_backoff_initial(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        assert state.backoff_seconds() == 0.0

    def test_backoff_sequence(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        expected = [1, 2, 4, 8, 16, 32, 60, 60]
        for i, exp in enumerate(expected):
            state.record_restart()
            assert state.backoff_seconds() == exp, f"step {i+1}: expected {exp}"

    def test_restarts_in_window_sliding(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        # Injeta 5 restarts antigos (fora da janela) e 3 recentes
        old_ts = time.monotonic() - _FLAPPING_WINDOW_S - 10
        state.restart_timestamps = deque([old_ts] * 5)
        for _ in range(3):
            state.record_restart()
        assert state.restarts_in_window() == 3

    def test_flapping_detected_after_10_restarts(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        for _ in range(_FLAPPING_MAX_RESTARTS):
            state.record_restart()
        assert state.restarts_in_window() >= _FLAPPING_MAX_RESTARTS

    def test_no_flapping_if_old_restarts(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        # 9 restarts antigos + 1 recente = total 10, mas 9 estão fora da janela
        old_ts = time.monotonic() - _FLAPPING_WINDOW_S - 1
        state.restart_timestamps = deque([old_ts] * 9)
        state.record_restart()
        assert state.restarts_in_window() == 1  # só o recente conta

    def test_window_uses_deque_not_reset(self) -> None:
        """Sliding window não reseta no início de cada janela."""
        state = _WorkerState(worker=_FakeWorker())
        # 5 restarts recentes em rápida sucessão
        for _ in range(5):
            state.record_restart()
        assert state.restarts_in_window() == 5

    def test_disabled_state_not_modified_by_record(self) -> None:
        state = _WorkerState(worker=_FakeWorker(), disabled=True)
        before = state.restarts_in_window()
        state.record_restart()
        # disabled não impede gravação, mas o supervisor verifica disabled antes de chamar
        assert state.restarts_in_window() == before + 1


# ── _is_pid_alive ─────────────────────────────────────────────────────────────

class TestIsPidAlive:
    def test_current_process_alive(self) -> None:
        import os
        assert _is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self) -> None:
        assert _is_pid_alive(99999999) is False

    def test_zero_pid(self) -> None:
        assert _is_pid_alive(0) is False

    def test_negative_pid(self) -> None:
        assert _is_pid_alive(-1) is False


# ── sd_notify ─────────────────────────────────────────────────────────────────

class TestSdNotify:
    def test_no_op_without_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
        _sd_notify("READY=1")  # deve ser silencioso

    def test_abstract_socket_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Testa que @... é convertido em socket abstrato sem erro de conexão."""
        monkeypatch.setenv("NOTIFY_SOCKET", "@/nonexistent.socket")
        # Vai falhar ao conectar, mas não deve levantar exceção
        _sd_notify("WATCHDOG=1")


# ── Backoff máximo ─────────────────────────────────────────────────────────────

def test_backoff_caps_at_60() -> None:
    state = _WorkerState(worker=_FakeWorker())
    for _ in range(20):
        state.record_restart()
    assert state.backoff_seconds() == 60.0


# ── C2: restart com attempt=1 e backoff=1s ───────────────────────────────────

class TestFirstRestartC2:
    def test_first_restart_has_attempt_1(self) -> None:
        """C2: primeiro restart → restarts_in_window() == 1."""
        state = _WorkerState(worker=_FakeWorker())
        state.record_restart()
        assert state.restarts_in_window() == 1

    def test_first_restart_backoff_is_1s(self) -> None:
        """C2: backoff do primeiro restart deve ser 1s."""
        state = _WorkerState(worker=_FakeWorker())
        state.record_restart()
        assert state.backoff_seconds() == _BACKOFF_SEQUENCE[0]

    def test_restart_recorded_after_record_restart(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        assert state.restarts_in_window() == 0
        state.record_restart()
        assert state.restarts_in_window() == 1

    def test_last_restart_at_updated(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        before = time.monotonic()
        state.record_restart()
        assert state.last_restart_at >= before


# ── C3: flapping detection ────────────────────────────────────────────────────

class TestFlappingDetectionC3:
    def test_exactly_10_restarts_triggers_flapping_threshold(self) -> None:
        """C3: ao atingir FLAPPING_MAX_RESTARTS o threshold é cumprido."""
        state = _WorkerState(worker=_FakeWorker())
        for _ in range(_FLAPPING_MAX_RESTARTS):
            state.record_restart()
        assert state.restarts_in_window() >= _FLAPPING_MAX_RESTARTS

    def test_11_restarts_above_threshold(self) -> None:
        state = _WorkerState(worker=_FakeWorker())
        for _ in range(_FLAPPING_MAX_RESTARTS + 1):
            state.record_restart()
        assert state.restarts_in_window() > _FLAPPING_MAX_RESTARTS

    def test_restarts_outside_window_dont_count(self) -> None:
        """C3: restarts com >10min não entram no cálculo."""
        state = _WorkerState(worker=_FakeWorker())
        old = time.monotonic() - _FLAPPING_WINDOW_S - 5
        state.restart_timestamps = deque([old] * (_FLAPPING_MAX_RESTARTS + 1))
        assert state.restarts_in_window() == 0

    def test_disabled_worker_is_not_restarted(self) -> None:
        """C3: worker.disabled impede novos forks (verificado no supervisor)."""
        state = _WorkerState(worker=_FakeWorker(), disabled=True)
        assert state.disabled is True


# ── _is_pid_alive com fork real ────────────────────────────────────────────────

class TestIsPidAliveWithFork:
    def test_forked_child_is_alive(self) -> None:
        """Filho vivo detectado por _is_pid_alive."""
        pid = os.fork()
        if pid == 0:
            time.sleep(5)
            os._exit(0)
        try:
            assert _is_pid_alive(pid) is True
        finally:
            os.kill(pid, 9)
            os.waitpid(pid, 0)

    def test_killed_child_not_alive(self) -> None:
        """Filho morto (SIGKILL) detectado por _is_pid_alive."""
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        assert _is_pid_alive(pid) is False
