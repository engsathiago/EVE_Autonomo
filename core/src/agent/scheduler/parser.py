"""
Converte expressões em linguagem natural para cron expressions validadas.

Validação dupla:
1. Sintática: croniter.is_valid()
2. Semântica: calcula 3 próximas execuções e verifica que são datas razoáveis
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from croniter import croniter

from agent.observability.logger import get_logger

log = get_logger(__name__)

# Prompt minimalista: manter tokens baixos (usado com modelo barato)
_PARSER_PROMPT = """\
Convert the natural language schedule to a valid cron expression (5 fields).
Reply with ONLY the cron expression, nothing else.

Examples:
- "every day at 8am" → "0 8 * * *"
- "every monday at 9am" → "0 9 * * 1"
- "every 30 minutes" → "*/30 * * * *"
- "every 1st of month" → "0 0 1 * *"
- "weekdays at 6pm" → "0 18 * * 1-5"
- "toda segunda às 9h" → "0 9 * * 1"
- "a cada 2 minutos" → "*/2 * * * *"
- "todo dia às 8h" → "0 8 * * *"

Schedule: {expr}
Cron:"""

_CRON_PATTERN = re.compile(r"^\s*([\d\*\/,\-]+\s+){4}[\d\*\/,\-]+\s*$")

_YEAR_MIN = 2020
_YEAR_MAX = 2100


class CronParseError(Exception):
    pass


async def parse_natural(expression: str, llm: Any) -> str:
    """
    Converte linguagem natural → cron expression.

    Args:
        expression: texto como "toda segunda às 9h"
        llm: qualquer objeto com método `complete(prompt, max_tokens, temperature) → str`
             ou `chat(system, messages, max_tokens)` compatível com ModelRouter.

    Returns:
        cron expression validada (5 campos)

    Raises:
        CronParseError: se LLM retornar expressão inválida após limpeza
    """
    prompt = _PARSER_PROMPT.format(expr=expression)

    try:
        # Tenta interface ModelRouter (chat)
        if hasattr(llm, "chat"):
            response = await llm.chat(
                system="You are a cron expression converter. Reply only with the cron expression.",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
            )
            raw = response.text.strip()
        else:
            raw = (await llm.complete(prompt, max_tokens=50, temperature=0)).strip()
    except Exception as exc:
        raise CronParseError(f"LLM indisponível para parse de cron: {exc}") from exc

    cron_expr = _extract_cron(raw)
    _validate_cron(cron_expr, original=expression)
    return cron_expr


def _extract_cron(raw: str) -> str:
    """Extrai os 5 campos cron do texto retornado pelo LLM."""
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    for line in lines:
        if _CRON_PATTERN.match(line):
            return " ".join(line.split())
    # Fallback: tenta pegar os 5 últimos tokens do texto
    tokens = raw.strip().split()
    if len(tokens) >= 5:
        candidate = " ".join(tokens[-5:])
        if _CRON_PATTERN.match(candidate):
            return candidate
    raise CronParseError(f"Não foi possível extrair cron expression de: {repr(raw)}")


def _validate_cron(expr: str, original: str) -> None:
    """Validação sintática + semântica."""
    if not croniter.is_valid(expr):
        raise CronParseError(f"Expressão cron inválida '{expr}' (original: '{original}')")

    # Validação semântica: calcula 3 próximas execuções
    base = datetime.now(tz=UTC)
    it = croniter(expr, base)
    for _ in range(3):
        next_dt = it.get_next(datetime)
        if not (_YEAR_MIN <= next_dt.year <= _YEAR_MAX):
            raise CronParseError(f"Expressão cron '{expr}' produz data implausível: {next_dt}")


def next_runs(expr: str, n: int = 5) -> list[datetime]:
    """Calcula as próximas N execuções a partir de agora."""
    base = datetime.now(tz=UTC)
    it = croniter(expr, base)
    return [it.get_next(datetime) for _ in range(n)]
