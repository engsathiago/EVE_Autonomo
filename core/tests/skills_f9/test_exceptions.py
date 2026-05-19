"""Testes das exceções F9."""
from __future__ import annotations

from agent.skills.exceptions import (
    SkillAlreadyExists,
    SkillInputInvalid,
    SkillNotActive,
    SkillNotFound,
    SkillOutputInvalid,
    SkillSynthesisFailed,
    SkillValidationFailed,
)


def test_skill_not_found_message() -> None:
    exc = SkillNotFound("my_skill")
    assert "my_skill" in str(exc)
    assert exc.slug == "my_skill"


def test_skill_not_active_message() -> None:
    exc = SkillNotActive("my_skill", "pending")
    assert "pending" in str(exc)
    assert exc.status == "pending"


def test_skill_validation_failed() -> None:
    exc = SkillValidationFailed("slug", "ruff error")
    assert "ruff error" in str(exc)
    assert exc.reason == "ruff error"


def test_skill_input_invalid() -> None:
    exc = SkillInputInvalid("slug", "campo ausente")
    assert "campo ausente" in str(exc)


def test_skill_output_invalid() -> None:
    exc = SkillOutputInvalid("slug", "campo obrigatório ausente")
    assert "obrigatório" in str(exc)


def test_skill_synthesis_failed() -> None:
    exc = SkillSynthesisFailed("LLM não respondeu")
    assert "LLM" in str(exc)


def test_skill_already_exists() -> None:
    exc = SkillAlreadyExists("slug")
    assert "slug" in str(exc)
