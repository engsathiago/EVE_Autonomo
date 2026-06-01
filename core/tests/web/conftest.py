"""Fixtures compartilhados para testes web."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_rate_counters():
    """Limpa rate limit counters entre testes para evitar 429 falsos."""
    from agent.web.server import _rate_counters

    _rate_counters.clear()
    yield
    _rate_counters.clear()
