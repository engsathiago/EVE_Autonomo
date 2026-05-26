"""
Supervisor de processos do agente (F10).

Faz fork dos 4 workers, monitora liveness, reinicia em crash com backoff
exponencial, detecta flapping (10 restarts em 10 min), e propaga SIGTERM
com graceful shutdown de 30s.

Integração systemd:
  - Envia sd_notify READY=1 via UNIX socket após todos os workers subirem.
  - Envia WATCHDOG=1 a cada WATCHDOG_INTERVAL_S (default 10s).
  - Escreve PID em /var/run/agent.pid.

Compatibilidade:
  - POSIX (Linux/macOS): os.fork() — worker herda espaço de endereçamento;
    deve reinicializar event loops e conexões assíncronas no processo filho.
  - Windows: multiprocessing.Process — usa spawn, sem herança; worker deve
    ser importável e serializável (sem closures em __init__).
"""

from __future__ import annotations

import collections
import json
import os
import platform
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.deploy.workers.base import Worker

# ── Constantes ────────────────────────────────────────────────────────────────

_MONITOR_INTERVAL_S = 5
_GRACEFUL_TIMEOUT_S = 30
_WATCHDOG_INTERVAL_S = int(os.environ.get("AGENT_WATCHDOG_INTERVAL_SECONDS", "10"))
_FLAPPING_MAX_RESTARTS = int(os.environ.get("AGENT_RESTART_MAX_PER_10MIN", "10"))
_FLAPPING_WINDOW_S = 600  # 10 minutos

# Backoff: 1, 2, 4, 8, 16, 32, 60, 60, 60, ...
_BACKOFF_SEQUENCE = [1, 2, 4, 8, 16, 32, 60]

_IS_WINDOWS = platform.system() == "Windows"


# ── sd_notify ─────────────────────────────────────────────────────────────────


def _sd_notify(msg: str) -> None:
    """Envia notificação ao systemd via NOTIFY_SOCKET.

    Não usa python-systemd; implementa o protocolo UNIX socket diretamente.
    É um no-op silencioso quando NOTIFY_SOCKET não está definido (fora do systemd).
    """
    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        return
    import socket

    # Sockets abstratos começam com '@' no systemd; Python usa '\0'
    addr = "\0" + sock_path[1:] if sock_path.startswith("@") else sock_path
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(msg.encode())
    except OSError:
        pass


# ── Estado por worker ─────────────────────────────────────────────────────────


@dataclass
class _WorkerState:
    worker: Worker
    pid: int = 0
    started_at: float = 0.0
    last_restart_at: float = 0.0
    restart_timestamps: collections.deque = field(default_factory=lambda: collections.deque())
    disabled: bool = False

    def backoff_seconds(self) -> float:
        """Retorna o backoff para o próximo restart.

        Chamada APÓS record_restart(), então n=1 no primeiro restart.
        idx = n-1 para mapear o 1° restart → _BACKOFF_SEQUENCE[0] = 1s.
        """
        n = len(self.restart_timestamps)
        if n == 0:
            return 0.0
        idx = min(n - 1, len(_BACKOFF_SEQUENCE) - 1)
        return _BACKOFF_SEQUENCE[idx]

    def record_restart(self) -> None:
        now = time.monotonic()
        self.restart_timestamps.append(now)
        self._prune_window(now)
        self.last_restart_at = now

    def restarts_in_window(self) -> int:
        self._prune_window(time.monotonic())
        return len(self.restart_timestamps)

    def _prune_window(self, now: float) -> None:
        cutoff = now - _FLAPPING_WINDOW_S
        while self.restart_timestamps and self.restart_timestamps[0] < cutoff:
            self.restart_timestamps.popleft()


# ── SQLite helper (síncrono — chamado do loop principal) ──────────────────────


def _get_db_path() -> str:
    return os.environ.get(
        "AGENT_DB_SQLITE",
        str(Path(__file__).parents[4] / "agent.db"),
    )


def _db_record_event(
    kind: str,
    worker: str | None,
    detail: dict,
    success: bool,
) -> None:
    try:
        conn = sqlite3.connect(_get_db_path())
        conn.execute(
            "INSERT INTO deploy_events (kind, worker, detail, success) VALUES (?,?,?,?)",
            (kind, worker, json.dumps(detail), int(success)),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # falha ao gravar evento não deve derrubar o supervisor


def _db_update_worker_health(
    worker_name: str,
    pid: int,
    started_at: float | None,
    restarts: int,
    state: str,
) -> None:
    try:
        conn = sqlite3.connect(_get_db_path())
        started_iso = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)) if started_at else None
        )
        conn.execute(
            """
            INSERT INTO worker_health (worker, pid, started_at, last_seen, restarts, state)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(worker) DO UPDATE SET
                pid=excluded.pid,
                started_at=COALESCE(excluded.started_at, started_at),
                last_seen=CURRENT_TIMESTAMP,
                restarts=excluded.restarts,
                state=excluded.state
            """,
            (worker_name, pid, started_iso, restarts, state),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Fork / spawn ──────────────────────────────────────────────────────────────


def _fork_worker(worker: Worker) -> int:
    """Cria processo filho para o worker. Retorna PID do filho."""
    if _IS_WINDOWS:
        import multiprocessing

        p = multiprocessing.Process(target=_run_worker_sync, args=(worker,), daemon=False)
        p.start()
        assert p.pid is not None
        return p.pid

    pid = os.fork()
    if pid == 0:
        # Processo filho
        _reset_signals_child()
        _run_worker_sync(worker)
        os._exit(0)

    return pid  # processo pai — retorna PID do filho


def _reset_signals_child() -> None:
    """Restaura handlers de sinal no filho após fork."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def _run_worker_sync(worker: Worker) -> None:
    """Ponto de entrada síncrono no processo filho."""
    import asyncio

    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Loga no stderr do filho; o pai detectará a saída anormal via waitpid
        print(f"[worker:{worker.name}] unhandled error: {exc}", file=sys.stderr)
        sys.exit(1)


# ── Supervisor ────────────────────────────────────────────────────────────────


class Supervisor:
    """Gerencia N workers: fork, monitor, restart com backoff, flapping detection."""

    def __init__(
        self,
        workers: list[Worker],
        pid_file: str | None = None,
    ) -> None:
        self._states: list[_WorkerState] = [_WorkerState(worker=w) for w in workers]
        self._pid_file = pid_file or os.environ.get("AGENT_PID_FILE", "/var/run/agent.pid")
        self._shutdown = False
        self._last_watchdog_s = 0.0

    # ── API pública ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Inicia todos os workers e entra no loop de monitoramento.

        Retorna somente quando todos os workers encerram (shutdown normal)
        ou quando o processo recebe SIGTERM/SIGINT.
        """
        self._write_pid()
        self._setup_signals()

        # Faz fork de todos os workers
        for state in self._states:
            if not state.disabled:
                self._start_worker(state)

        # Aguarda todos subirem (heurística: 2s) e notifica systemd
        time.sleep(2)
        _sd_notify("READY=1")

        self._monitor_loop()
        self._remove_pid()

    # ── Internos ──────────────────────────────────────────────────────────────

    def _start_worker(self, state: _WorkerState) -> None:
        state.pid = _fork_worker(state.worker)
        state.started_at = time.monotonic()
        _db_update_worker_health(state.worker.name, state.pid, state.started_at, 0, "running")
        _db_record_event("start", state.worker.name, {"pid": state.pid}, True)
        _log(f"worker.started worker={state.worker.name} pid={state.pid}")

    def _monitor_loop(self) -> None:
        while not self._shutdown:
            # Envia watchdog para systemd a cada WATCHDOG_INTERVAL_S
            now = time.monotonic()
            if now - self._last_watchdog_s >= _WATCHDOG_INTERVAL_S:
                _sd_notify("WATCHDOG=1")
                self._last_watchdog_s = now

            for state in self._states:
                if state.disabled or self._shutdown:
                    continue
                if not _is_pid_alive(state.pid):
                    self._handle_worker_died(state)

            time.sleep(_MONITOR_INTERVAL_S)

        self._graceful_shutdown()

    def _handle_worker_died(self, state: _WorkerState) -> None:
        exit_code = _reap_child(state.pid)
        _db_record_event(
            "crash", state.worker.name, {"pid": state.pid, "exit_code": exit_code}, False
        )
        _log(f"worker.died worker={state.worker.name} pid={state.pid} exit={exit_code}")

        state.record_restart()
        n_in_window = state.restarts_in_window()

        # Flapping: >= 10 restarts em 10 minutos
        if n_in_window >= _FLAPPING_MAX_RESTARTS:
            state.disabled = True
            _db_update_worker_health(state.worker.name, 0, None, n_in_window, "flapping")
            _db_record_event(
                "crash",
                state.worker.name,
                {"event": "worker.flapping", "restarts_in_window": n_in_window},
                False,
            )
            _log(
                f"worker.flapping worker={state.worker.name} "
                f"restarts_in_window={n_in_window} — DESATIVADO"
            )
            return

        backoff = state.backoff_seconds()
        attempt = n_in_window
        _log(f"worker.restarting worker={state.worker.name} attempt={attempt} backoff={backoff}s")
        _db_update_worker_health(state.worker.name, 0, None, n_in_window, "stopped")
        _db_record_event(
            "restart",
            state.worker.name,
            {"attempt": attempt, "backoff_seconds": backoff},
            True,
        )

        if backoff > 0:
            time.sleep(backoff)

        self._start_worker(state)

    def _graceful_shutdown(self) -> None:
        _log("supervisor.shutdown: enviando SIGTERM aos workers")
        _sd_notify("STOPPING=1")

        for state in self._states:
            if state.pid and _is_pid_alive(state.pid):
                try:
                    os.kill(state.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

        deadline = time.monotonic() + _GRACEFUL_TIMEOUT_S
        while time.monotonic() < deadline:
            alive = [s for s in self._states if s.pid and _is_pid_alive(s.pid)]
            if not alive:
                break
            time.sleep(0.5)

        # SIGKILL nos que restaram
        for state in self._states:
            if state.pid and _is_pid_alive(state.pid):
                _log(f"supervisor.sigkill worker={state.worker.name} pid={state.pid}")
                try:
                    os.kill(state.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            _db_update_worker_health(state.worker.name, 0, None, 0, "stopped")
            _db_record_event("stop", state.worker.name, {"graceful": True}, True)

    def _setup_signals(self) -> None:
        def _handle_term(signum: int, frame: object) -> None:
            _log(f"supervisor: recebeu sinal {signum}")
            self._shutdown = True

        signal.signal(signal.SIGTERM, _handle_term)
        signal.signal(signal.SIGINT, _handle_term)

    def _write_pid(self) -> None:
        try:
            Path(self._pid_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self._pid_file).write_text(str(os.getpid()))
        except OSError:
            pass

    def _remove_pid(self) -> None:
        try:
            Path(self._pid_file).unlink(missing_ok=True)
        except OSError:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # processo existe mas não temos permissão de sinalizar


def _reap_child(pid: int) -> int:
    """Coleta o exit code de um processo filho sem bloquear."""
    try:
        _, status = os.waitpid(pid, os.WNOHANG)
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        if os.WIFSIGNALED(status):
            return -os.WTERMSIG(status)
        return -1
    except ChildProcessError:
        return -1
    except AttributeError:
        # Windows não tem WNOHANG da mesma forma
        return -1


def _log(msg: str) -> None:
    """Log mínimo síncrono para o supervisor (sem structlog no processo pai)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} [supervisor] {msg}", flush=True)


# ── Entrypoint ────────────────────────────────────────────────────────────────


def main() -> None:
    """Usado por `python -m agent.deploy.supervisor` no systemd."""
    from agent.deploy.workers.api_worker import ApiWorker
    from agent.deploy.workers.heartbeat_worker import HeartbeatWorker
    from agent.deploy.workers.orchestrator_worker import OrchestratorWorker
    from agent.deploy.workers.scheduler_worker import SchedulerWorker

    host = os.environ.get("AGENT_API_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENT_API_PORT", "8000"))
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    api_url = f"http://{host}:{port}"

    workers: list[Worker] = [
        ApiWorker(host=host, port=port),
        OrchestratorWorker(redis_url=redis_url),
        SchedulerWorker(redis_url=redis_url),
        HeartbeatWorker(api_url=api_url),
    ]

    enabled_names_env = os.environ.get("AGENT_WORKERS", "")
    if enabled_names_env:
        enabled = set(enabled_names_env.split(","))
        workers = [w for w in workers if w.name in enabled]

    pid_file = os.environ.get("AGENT_PID_FILE", "/var/run/agent.pid")
    Supervisor(workers, pid_file=pid_file).run()


if __name__ == "__main__":
    main()
