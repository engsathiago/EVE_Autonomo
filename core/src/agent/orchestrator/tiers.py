"""
Classificação de tiers de execução.

Cache em memória (TTL 5min) reduz custo do classifier — 1 chamada LLM por
mensagem única, mas mensagens idênticas dentro do TTL são reutilizadas.
"""

from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import TYPE_CHECKING

from agent.observability.logger import get_logger

if TYPE_CHECKING:
    from agent.models.router import ModelRouter

log = get_logger(__name__)

CLASSIFIER_PROMPT = """\
Classify the user task into ONE tier:
- INSTANT: pure conversation, definition, opinion. No tool needed.
- FAST: needs 1 tool call. Single fact lookup, single file read.
- STRATEGIC: 2-5 steps, single domain (e.g. research one topic, write a report).
- EPIC: independent parallel work (e.g. monitor 3 sites + summarize each).

Reply with ONE word: INSTANT, FAST, STRATEGIC, or EPIC.

Task: {task}"""


class ExecutionTier(str, Enum):
    INSTANT = "INSTANT"
    FAST = "FAST"
    STRATEGIC = "STRATEGIC"
    EPIC = "EPIC"


_VALID_TIERS = {t.value for t in ExecutionTier}
_DEFAULT_ON_PARSE_ERROR = ExecutionTier.STRATEGIC  # mais seguro que EPIC


class TierClassifier:
    def __init__(
        self,
        model_router: ModelRouter,
        model: str = "anthropic:claude-haiku-4-5",
        max_tokens: int = 200,
        cache_ttl_s: int = 300,
    ) -> None:
        self._router = model_router
        self._model = model
        self._max_tokens = max_tokens
        self._cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[ExecutionTier, float]] = {}

    async def classify(self, task_content: str) -> ExecutionTier:
        cache_key = _hash(task_content)
        cached = self._cache.get(cache_key)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl_s:
            log.debug("orchestrator.tier.cache_hit", key=cache_key[:8])
            return cached[0]

        t0 = time.monotonic()
        tier = await self._call_llm(task_content)
        latency_ms = int((time.monotonic() - t0) * 1000)

        self._cache[cache_key] = (tier, time.monotonic())
        log.info("orchestrator.classified", tier=tier.value, latency_ms=latency_ms)
        return tier

    async def _call_llm(self, task_content: str) -> ExecutionTier:
        prompt = CLASSIFIER_PROMPT.format(task=task_content[:1000])
        try:
            response = await self._router.chat(
                system="You are a task classifier. Reply with one word only.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self._max_tokens,
                model=self._model,
            )
            raw = response.text.strip().upper()
            # Extrai apenas a palavra válida (LLM pode retornar texto extra)
            for word in raw.split():
                if word in _VALID_TIERS:
                    return ExecutionTier(word)
        except Exception as exc:
            log.warning("orchestrator.classifier.failed", error=str(exc))

        log.warning("orchestrator.tier.fallback", fallback=_DEFAULT_ON_PARSE_ERROR.value)
        return _DEFAULT_ON_PARSE_ERROR


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
