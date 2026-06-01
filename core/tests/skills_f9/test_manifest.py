"""Testes do SkillManifestF9 — C2: manifesto obrigatório."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.skills.manifest import NetworkPolicy, SkillManifestF9


def _valid_manifest(**kwargs: object) -> dict:
    base: dict = {
        "slug": "my_skill",
        "version": 1,
        "created_at": datetime.now(tz=UTC),
        "description": "Test skill",
        "embedding_text": "test skill embedding",
        "inputs_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        "outputs_schema": {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
        "sandbox_profile": "SKILL_DEV",
        "network_policy": {"allow_domains": []},
        "irreversible": False,
    }
    base.update(kwargs)
    return base


def test_valid_manifest() -> None:
    m = SkillManifestF9(**_valid_manifest())
    assert m.slug == "my_skill"
    assert m.sandbox_profile == "SKILL_DEV"


def test_missing_inputs_schema_raises() -> None:
    data = _valid_manifest()
    del data["inputs_schema"]
    with pytest.raises(Exception):
        SkillManifestF9(**data)


def test_missing_outputs_schema_raises() -> None:
    data = _valid_manifest()
    del data["outputs_schema"]
    with pytest.raises(Exception):
        SkillManifestF9(**data)


def test_missing_sandbox_profile_raises() -> None:
    data = _valid_manifest()
    del data["sandbox_profile"]
    with pytest.raises(Exception):
        SkillManifestF9(**data)


def test_missing_network_policy_raises() -> None:
    data = _valid_manifest()
    del data["network_policy"]
    with pytest.raises(Exception):
        SkillManifestF9(**data)


def test_invalid_sandbox_profile_raises() -> None:
    with pytest.raises(Exception, match="sandbox_profile"):
        SkillManifestF9(**_valid_manifest(sandbox_profile="OPEN"))


def test_open_network_policy_rejected() -> None:
    # skills auto-geradas não podem ter network_policy OPEN (wildcard)
    with pytest.raises(Exception):
        NetworkPolicy(allow_domains=["*"])


def test_invalid_slug_raises() -> None:
    with pytest.raises(Exception, match="slug"):
        SkillManifestF9(**_valid_manifest(slug="My Skill 123!"))


def test_inputs_schema_missing_type_raises() -> None:
    with pytest.raises(Exception, match="inputs_schema"):
        SkillManifestF9(**_valid_manifest(inputs_schema={"properties": {}}))


def test_all_profiles_valid() -> None:
    for profile in ("SKILL_DEV", "DEFAULT", "UNTRUSTED"):
        m = SkillManifestF9(**_valid_manifest(sandbox_profile=profile))
        assert m.sandbox_profile == profile
