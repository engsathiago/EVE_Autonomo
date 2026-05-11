# Importações lazy para evitar dependências obrigatórias no import do pacote.
# Fase 3 (template skills): SkillCreator, SkillManager, SkillManifest (schema.py)
# Fase 9 (auto-generated skills): SkillManifestF9, SkillRegistry, SkillRunner, etc.

from agent.skills.schema import SkillManifest, SkillMatch, SkillResult

__all__ = ["SkillManifest", "SkillMatch", "SkillResult"]


def __getattr__(name: str) -> object:
    if name == "SkillCreator":
        from agent.skills.creator import SkillCreator
        return SkillCreator
    if name == "SkillManager":
        from agent.skills.manager import SkillManager
        return SkillManager
    raise AttributeError(f"module 'agent.skills' has no attribute {name!r}")
