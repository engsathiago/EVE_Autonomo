"""Skill de exemplo (mock) para testes do SkillRunner — não é funcional de verdade."""
from __future__ import annotations


async def run(input: dict) -> dict:
    url = input.get("url", "")
    language = input.get("language", "pt")
    return {
        "transcript": f"exemplo de transcrição para {url} em {language}",
        "duration_seconds": 60,
    }
