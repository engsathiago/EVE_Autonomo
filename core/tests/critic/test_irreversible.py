"""Testa lista de IRREVERSIBLE_TOOLS e integração com SkillManifest."""

from __future__ import annotations

from agent.critic.irreversible import IRREVERSIBLE_TOOLS, is_irreversible
from agent.skills.schema import SkillManifest


def test_irreversible_tools_list_is_explicit() -> None:
    """Lista deve ser frozenset com ao menos os tools canônicos do spec."""
    required = {
        "send_telegram",
        "send_email",
        "post_social_media",
        "git_push",
        "fs_delete",
        "execute_shell",
        "transfer_money",
        "delete_record",
        "execute_sql_write",
    }
    assert required.issubset(IRREVERSIBLE_TOOLS), f"Tools ausentes: {required - IRREVERSIBLE_TOOLS}"


def test_irreversible_is_not_heuristic() -> None:
    """Tool não cadastrada não deve ser marcada como irreversível."""
    assert not is_irreversible("web_search")
    assert not is_irreversible("read_file")
    assert not is_irreversible("salvar_memoria")


def test_skill_must_declare_irreversible_to_be_critiqued() -> None:
    """
    Skill com irreversible=False não entra no Critic pelo campo do manifesto.
    Só tools na lista IRREVERSIBLE_TOOLS ativam o Critic automaticamente.
    """
    safe_skill = SkillManifest(
        name="minha_skill",
        description="skill de leitura",
        irreversible=False,
    )
    assert safe_skill.irreversible is False

    risky_skill = SkillManifest(
        name="skill_perigosa",
        description="skill que posta em redes sociais",
        irreversible=True,
    )
    assert risky_skill.irreversible is True

    # Campo padrão é False — compatibilidade com skills existentes (F3)
    legacy_skill = SkillManifest(name="legacy", description="skill antiga")
    assert legacy_skill.irreversible is False
