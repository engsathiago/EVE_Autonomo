"""Exceções da Fase 9: skills auto-geradas."""
from __future__ import annotations


class SkillNotFound(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Skill não encontrada: '{slug}'")
        self.slug = slug


class SkillNotActive(Exception):
    def __init__(self, slug: str, status: str) -> None:
        super().__init__(f"Skill '{slug}' não está ativa (status={status!r})")
        self.slug = slug
        self.status = status


class SkillValidationFailed(Exception):
    def __init__(self, slug: str, reason: str) -> None:
        super().__init__(f"Validação de '{slug}' falhou: {reason}")
        self.slug = slug
        self.reason = reason


class SkillInputInvalid(Exception):
    def __init__(self, slug: str, detail: str) -> None:
        super().__init__(f"Input inválido para skill '{slug}': {detail}")
        self.slug = slug
        self.detail = detail


class SkillOutputInvalid(Exception):
    def __init__(self, slug: str, detail: str) -> None:
        super().__init__(f"Output inválido de skill '{slug}': {detail}")
        self.slug = slug
        self.detail = detail


class SkillSynthesisFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Síntese de skill falhou: {reason}")
        self.reason = reason


class SkillAlreadyExists(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Skill '{slug}' já existe")
        self.slug = slug
