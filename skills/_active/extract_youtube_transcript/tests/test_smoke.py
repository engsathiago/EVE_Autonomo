"""Smoke test da skill extract_youtube_transcript (mock)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Permite importar skill.py de qualquer diretório
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_run_returns_transcript() -> None:
    from skill import run
    result = asyncio.run(run({"url": "https://youtube.com/watch?v=test"}))
    assert "transcript" in result
    assert "duration_seconds" in result
    assert isinstance(result["transcript"], str)
    assert isinstance(result["duration_seconds"], (int, float))


def test_run_uses_url() -> None:
    from skill import run
    result = asyncio.run(run({"url": "https://youtube.com/watch?v=abc123", "language": "en"}))
    assert "abc123" in result["transcript"]
