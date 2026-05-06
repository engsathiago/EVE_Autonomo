"""
Testes de cálculo de custo por invocação.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent.models.pricing import cost_usd


def test_anthropic_haiku_cost() -> None:
    # claude-haiku-4-5: $0.80/$4.00 por 1M
    c = cost_usd("anthropic:claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0)
    assert c == Decimal("0.800000")


def test_anthropic_haiku_output_cost() -> None:
    c = cost_usd("anthropic:claude-haiku-4-5", input_tokens=0, output_tokens=1_000_000)
    assert c == Decimal("4.000000")


def test_anthropic_sonnet_cost() -> None:
    # claude-sonnet-4-7: $3.00/$15.00 por 1M
    c = cost_usd("anthropic:claude-sonnet-4-7", input_tokens=500_000, output_tokens=500_000)
    assert c == Decimal("9.000000")


def test_openai_gpt4o_mini() -> None:
    # gpt-4o-mini: $0.15/$0.60 por 1M
    c = cost_usd("openai:gpt-4o-mini", input_tokens=100_000, output_tokens=100_000)
    assert float(c) == pytest.approx(0.075, rel=1e-5)


def test_ollama_always_zero() -> None:
    c = cost_usd("ollama:qwen2.5:32b", input_tokens=999_999, output_tokens=999_999)
    assert c == Decimal("0")


def test_ollama_zero_for_any_model() -> None:
    for alias in ["ollama:llama3.3:70b", "ollama:hermes3:8b", "ollama:deepseek-r1:14b"]:
        assert cost_usd(alias, 1_000_000, 1_000_000) == Decimal("0")


def test_openrouter_uses_provided_cost() -> None:
    c = cost_usd("openrouter:deepseek/deepseek-chat", 100, 100, openrouter_cost=0.001234)
    assert c == Decimal("0.001234")


def test_unknown_model_zero() -> None:
    c = cost_usd("anthropic:claude-unknown-99", 1_000_000, 1_000_000)
    assert c == Decimal("0")


def test_small_call_precision() -> None:
    """Chama com 82 tokens input + 341 output no haiku — resultado quantizado para 6 casas."""
    c = cost_usd("anthropic:claude-haiku-4-5", input_tokens=82, output_tokens=341)
    # 82 * 0.80/1M + 341 * 4.00/1M = 0.0000656 + 0.001364 = 0.0014296 → 0.001430 (6 casas)
    from decimal import Decimal
    assert c == Decimal("0.001430")
