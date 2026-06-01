"""
Testes de não-regressão: verifica que componentes da F6 não foram quebrados.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.orchestrator.tiers import ExecutionTier, TierClassifier
from agent.scheduler.worker import CronWorker


def test_orchestrator_tier_classification_unchanged() -> None:
    """TierClassifier ainda tem os 4 tiers e retorna ExecutionTier."""
    tiers = {t.value for t in ExecutionTier}
    assert tiers == {"INSTANT", "FAST", "STRATEGIC", "EPIC"}

    # Verifica que o cache TTL default não mudou
    router = MagicMock()
    classifier = TierClassifier(model_router=router)
    assert classifier._cache_ttl_s == 300  # 5 min


def test_subagent_isolation_unchanged() -> None:
    """SubAgentContext cria contexto isolado — só expõe tools_allowed."""
    from agent.subagents.context import SubAgentContext
    ctx = SubAgentContext(
        task="pesquisar concorrentes",
        tools_allowed=["web_search"],
        max_iterations=5,
        timeout_s=60,
    )
    # Campos definidos
    assert ctx.task == "pesquisar concorrentes"
    assert ctx.tools_allowed == ["web_search"]
    assert ctx.max_iterations == 5

    # System prompt menciona apenas as tools permitidas
    prompt = ctx.build_system_prompt()
    assert "web_search" in prompt
    assert "focused subagent" in prompt


def test_cron_persistence_unchanged() -> None:
    """CronWorker ainda usa _WORKER_REGISTRY e registra por id()."""
    from agent.scheduler.worker import _WORKER_REGISTRY

    scheduler = MagicMock()
    scheduler.running = False
    cron_store = MagicMock()
    task_store = MagicMock()
    orchestrator = MagicMock()

    worker = CronWorker(
        scheduler=scheduler,
        cron_store=cron_store,
        task_store=task_store,
        orchestrator=orchestrator,
    )

    assert worker._worker_id in _WORKER_REGISTRY
    assert _WORKER_REGISTRY[worker._worker_id] is worker

    # Cleanup
    _WORKER_REGISTRY.pop(worker._worker_id, None)
