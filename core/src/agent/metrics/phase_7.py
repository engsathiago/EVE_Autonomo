"""
Métricas da Fase 7 — Missões + Crítico.

Expõe em formato Prometheus via /metrics. Coletadas em memória (processo único).
A Web UI (F11) consumirá esses dados — aqui só definimos e atualizamos.

Alertas documentados nos docstrings (sem notificação de prod ainda):
- critic_approve_rate > 0.95 por 24h → critic possivelmente capturado
- critic_reject_rate > 0.40 por 24h → crítico paranoico ou tool mal classificada
- step_success_rate < 0.50 por 7d → planner gerando passos inviáveis
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agent.observability.logger import get_logger

log = get_logger(__name__)

_24H_S = 86400
_7D_S = 7 * _24H_S


@dataclass
class _TimedValue:
    value: float
    ts: float = field(default_factory=time.monotonic)


class _RollingCounter:
    """Contador com janela de tempo deslizante."""
    def __init__(self, window_s: float = _24H_S) -> None:
        self._window = window_s
        self._events: deque[float] = deque()

    def inc(self, n: int = 1) -> None:
        now = time.monotonic()
        for _ in range(n):
            self._events.append(now)

    def value(self) -> int:
        cutoff = time.monotonic() - self._window
        while self._events and self._events[0] < cutoff:
            self._events.popleft()
        return len(self._events)


class _RollingHistogram:
    """Histograma simples com valores em janela deslizante."""
    def __init__(self, window_s: float = _24H_S) -> None:
        self._window = window_s
        self._data: deque[_TimedValue] = deque()

    def observe(self, value: float) -> None:
        self._data.append(_TimedValue(value=value))

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        while self._data and self._data[0].ts < cutoff:
            self._data.popleft()

    def p50(self) -> float:
        self._prune()
        if not self._data:
            return 0.0
        vals = sorted(v.value for v in self._data)
        return vals[len(vals) // 2]

    def p95(self) -> float:
        self._prune()
        if not self._data:
            return 0.0
        vals = sorted(v.value for v in self._data)
        return vals[int(len(vals) * 0.95)]

    def count(self) -> int:
        self._prune()
        return len(self._data)


class Phase7Metrics:
    """Singleton de métricas da F7. Atualizado pelos componentes."""

    def __init__(self) -> None:
        # Missões (gauges)
        self.missions_active: int = 0

        # Missões (contadores 24h)
        self._missions_completed = _RollingCounter()
        self._missions_failed = _RollingCounter()
        self._missions_abandoned = _RollingCounter()

        # Steps
        self._steps_per_tick: deque[tuple[int, float]] = deque()  # (count, ts)
        self._steps_done = _RollingCounter(window_s=_7D_S)
        self._steps_failed_counter = _RollingCounter(window_s=_7D_S)

        # Critic
        self._critic_total = _RollingCounter()
        self._critic_approve = _RollingCounter()
        self._critic_reject = _RollingCounter()
        self._critic_escalate = _RollingCounter()
        self._critic_latency = _RollingHistogram()
        self._critic_cost = _RollingHistogram()

        # Memória reflexiva
        self.reflexive_insights_total: int = 0
        self.reflexive_forgotten_count: int = 0
        self._reflexive_recalls = _RollingCounter()

    # ── Mission events ────────────────────────────────────────────────────────

    def mission_completed(self) -> None:
        self._missions_completed.inc()

    def mission_failed(self) -> None:
        self._missions_failed.inc()

    def mission_abandoned(self) -> None:
        self._missions_abandoned.inc()

    def steps_dispatched(self, count: int) -> None:
        self._steps_per_tick.append((count, time.monotonic()))
        # prune > 24h
        cutoff = time.monotonic() - _24H_S
        while self._steps_per_tick and self._steps_per_tick[0][1] < cutoff:
            self._steps_per_tick.popleft()

    def step_done(self) -> None:
        self._steps_done.inc()

    def step_failed(self) -> None:
        self._steps_failed_counter.inc()

    # ── Critic events ─────────────────────────────────────────────────────────

    def critic_evaluated(self, verdict: str, latency_ms: int, cost_usd: float) -> None:
        self._critic_total.inc()
        self._critic_latency.observe(latency_ms)
        self._critic_cost.observe(cost_usd)
        match verdict:
            case "approve" | "approve_with_mitigation":
                self._critic_approve.inc()
            case "reject":
                self._critic_reject.inc()
            case "escalate":
                self._critic_escalate.inc()

        self._check_alerts()

    # ── Reflexive memory events ───────────────────────────────────────────────

    def insight_added(self) -> None:
        self.reflexive_insights_total += 1

    def insight_forgotten(self) -> None:
        self.reflexive_forgotten_count += 1

    def insight_recalled(self) -> None:
        self._reflexive_recalls.inc()

    # ── Alerts ───────────────────────────────────────────────────────────────

    def _check_alerts(self) -> None:
        total = self._critic_total.value()
        if total < 10:
            return

        approve_rate = self._critic_approve.value() / total
        reject_rate = self._critic_reject.value() / total
        success_total = self._steps_done.value() + self._steps_failed_counter.value()
        step_success = self._steps_done.value() / success_total if success_total > 0 else 1.0

        if approve_rate > 0.95:
            log.warning(
                "metrics.alert.critic_rubber_stamp",
                approve_rate=round(approve_rate, 3),
                message="Critic aprovando >95% das decisões — investigar captura",
            )
        if reject_rate > 0.40:
            log.warning(
                "metrics.alert.critic_paranoid",
                reject_rate=round(reject_rate, 3),
                message="Critic rejeitando >40% das decisões — crítico paranoico ou planner ruim",
            )
        if step_success < 0.50:
            log.warning(
                "metrics.alert.low_step_success",
                step_success_rate=round(step_success, 3),
                message="Taxa de sucesso de steps <50% — planner gerando passos inviáveis",
            )

    # ── Snapshot (para /metrics e CLI) ───────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        total_critic = self._critic_total.value()
        steps_done = self._steps_done.value()
        steps_fail = self._steps_failed_counter.value()
        steps_total = steps_done + steps_fail

        return {
            "missions_active": self.missions_active,
            "missions_completed_24h": self._missions_completed.value(),
            "missions_failed_24h": self._missions_failed.value(),
            "missions_abandoned_24h": self._missions_abandoned.value(),
            "steps_per_tick_avg": (
                sum(c for c, _ in self._steps_per_tick) / len(self._steps_per_tick)
                if self._steps_per_tick else 0.0
            ),
            "step_success_rate_7d": steps_done / steps_total if steps_total > 0 else 1.0,
            "critic_evaluations_total_24h": total_critic,
            "critic_approve_rate": (
                self._critic_approve.value() / total_critic if total_critic else 0.0
            ),
            "critic_reject_rate": (
                self._critic_reject.value() / total_critic if total_critic else 0.0
            ),
            "critic_escalate_rate": (
                self._critic_escalate.value() / total_critic if total_critic else 0.0
            ),
            "critic_latency_p50_ms": self._critic_latency.p50(),
            "critic_latency_p95_ms": self._critic_latency.p95(),
            "critic_cost_usd_avg": (
                sum(v.value for v in self._critic_cost._data) / len(self._critic_cost._data)
                if self._critic_cost._data else 0.0
            ),
            "reflexive_insights_total": self.reflexive_insights_total,
            "reflexive_recall_count_24h": self._reflexive_recalls.value(),
            "reflexive_forgotten_count": self.reflexive_forgotten_count,
        }

    def prometheus_text(self) -> str:
        """Exporta no formato Prometheus text (para /metrics)."""
        snap = self.snapshot()
        lines: list[str] = []
        for key, val in snap.items():
            metric_name = f"agent_f7_{key}"
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{metric_name} {val:.6f}")
        return "\n".join(lines) + "\n"


# Singleton global — importado pelos componentes
metrics = Phase7Metrics()
