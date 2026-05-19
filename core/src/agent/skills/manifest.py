"""
SkillManifest (Fase 9): schema Pydantic para skills auto-geradas (.py).

Diferente do SkillManifest da Fase 3 (schema.py) que é para skills .md/template.
Este manifesto é declarativo, versionável, e contém política de sandbox obrigatória.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class NetworkPolicy(BaseModel):
    allow_domains: list[str] = []

    @model_validator(mode="after")
    def _no_open_network(self) -> "NetworkPolicy":
        # Abre a rede de forma irrestrita é anti-padrão proibido no spec §14
        if "*" in self.allow_domains or "0.0.0.0" in self.allow_domains:
            raise ValueError(
                "network_policy não pode ter '*' ou '0.0.0.0' — "
                "skills auto-geradas não podem ter network_policy OPEN"
            )
        return self


_VALID_SANDBOX_PROFILES = {"SKILL_DEV", "DEFAULT", "UNTRUSTED"}


class SkillStats(BaseModel):
    executions: int = 0
    successes: int = 0
    failures: int = 0
    last_used_at: datetime | None = None
    avg_duration_seconds: float | None = None


class SkillProvenance(BaseModel):
    pattern_source_executions: list[str] = []
    synthesized_from_template: str = "ad_hoc"
    critic_approval_id: str | None = None


class SkillManifestF9(BaseModel):
    """Manifesto de skill auto-gerada (Fase 9). Validação dura — campo ausente = rejeição."""
    slug: str
    version: int = 1
    created_at: datetime
    created_by: str = "synthesizer"
    description: str
    embedding_text: str

    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]

    sandbox_profile: str
    network_policy: NetworkPolicy
    irreversible: bool = False
    estimated_wall_time_seconds: int = 30
    estimated_memory_mb: int = 256

    stats: SkillStats = SkillStats()
    provenance: SkillProvenance = SkillProvenance()

    @field_validator("sandbox_profile")
    @classmethod
    def _validate_profile(cls, v: str) -> str:
        if v not in _VALID_SANDBOX_PROFILES:
            raise ValueError(
                f"sandbox_profile={v!r} inválido. Válidos: {_VALID_SANDBOX_PROFILES}"
            )
        return v

    @field_validator("inputs_schema")
    @classmethod
    def _validate_inputs_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "type" not in v or "properties" not in v:
            raise ValueError("inputs_schema deve ter 'type' e 'properties'")
        return v

    @field_validator("outputs_schema")
    @classmethod
    def _validate_outputs_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "type" not in v or "properties" not in v:
            raise ValueError("outputs_schema deve ter 'type' e 'properties'")
        return v

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z][a-z0-9_]{1,63}$", v):
            raise ValueError(
                f"slug={v!r} inválido — deve ser snake_case, [a-z][a-z0-9_]{{1,63}}"
            )
        return v


def load_manifest_from_yaml(path: "str | import_pathlib_Path") -> SkillManifestF9:  # type: ignore[name-defined]
    """Carrega e valida manifest.yaml de uma skill. Lança ValueError se inválido."""
    import yaml  # type: ignore[import-untyped]
    from pathlib import Path
    data = yaml.safe_load(Path(str(path)).read_text())
    return SkillManifestF9(**data)


def manifest_to_dict(manifest: SkillManifestF9) -> dict[str, Any]:
    return manifest.model_dump(mode="json")
