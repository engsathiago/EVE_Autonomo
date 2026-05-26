"""
Tabela de preços por modelo (USD/1M tokens). Última atualização: 2026-05.
"""

from __future__ import annotations

from decimal import Decimal

# (input_per_1m_usd, output_per_1m_usd)
PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    # Anthropic
    "anthropic:claude-sonnet-4-7": (3.00, 15.00),
    "anthropic:claude-opus-4-7": (15.00, 75.00),
    "anthropic:claude-haiku-4-5": (0.80, 4.00),
    "anthropic:claude-sonnet-4-6": (3.00, 15.00),
    # OpenAI
    "openai:gpt-4o": (2.50, 10.00),
    "openai:gpt-4o-mini": (0.15, 0.60),
    # OpenRouter: custo vem direto no response (campo usage.cost)
    # Ollama: custo zero (local)
}


def cost_usd(
    model_alias: str,
    input_tokens: int,
    output_tokens: int,
    openrouter_cost: float | None = None,
) -> Decimal:
    """Calcula custo em USD para uma invocação.

    OpenRouter retorna 'usage.cost' no response — usar esse valor quando disponível.
    Modelos Ollama sempre retornam zero.
    Modelos desconhecidos retornam zero (não chuta).
    """
    if model_alias.startswith("ollama:"):
        return Decimal("0")

    if model_alias.startswith("openrouter:") and openrouter_cost is not None:
        return Decimal(str(openrouter_cost)).quantize(Decimal("0.000001"))

    rates = PRICING_USD_PER_1M.get(model_alias)
    if not rates:
        return Decimal("0")

    in_rate, out_rate = rates
    return (
        Decimal(input_tokens) * Decimal(str(in_rate)) / Decimal("1000000")
        + Decimal(output_tokens) * Decimal(str(out_rate)) / Decimal("1000000")
    ).quantize(Decimal("0.000001"))
