"""Helpers para full-text search em português via asyncpg."""

from __future__ import annotations


def plainto_tsquery_pt(term: str) -> str:
    """
    Retorna o fragmento SQL para tsquery em português com unaccent.
    Usado nas queries do store para evitar repetição.
    """
    # O unaccent e o plainto_tsquery são aplicados no lado SQL;
    # este helper existe para documentar o padrão e facilitar testes.
    return term


def ts_rank_sql(alias: str = "score") -> str:
    return f"ts_rank(tsv, plainto_tsquery('portuguese', unaccent($1))) AS {alias}"


def tsv_match_sql() -> str:
    return "tsv @@ plainto_tsquery('portuguese', unaccent($1))"
