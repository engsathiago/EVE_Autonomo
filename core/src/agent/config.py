import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto: sobe 3 níveis de core/src/agent/config.py → agent/
_PROJECT_ROOT = Path(__file__).parents[3]
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Carrega yaml expandindo variáveis de ambiente ${VAR} no texto."""
    raw = path.read_text()
    expanded = os.path.expandvars(raw)
    return yaml.safe_load(expanded) or {}


class SkillsSettings(BaseSettings):
    skills_dir: str = "core/src/agent/skills"
    skills_drafts_dir: str = "core/src/agent/skills/_drafts"
    skills_auto_create: bool = True
    skills_auto_create_threshold: int = 3
    skills_embedding_cache_dir: str = ".cache/skill_embeddings"
    skills_match_k: int = 3


class AgentSettings(BaseSettings):
    name: str = "Eve"
    default_model: str = "claude-haiku-4-5"
    reflector_model: str = "claude-sonnet-4-6"
    max_iterations: int = 15
    reflection_every: int = 3
    context_compression_threshold: float = 0.5
    workspace_paths: list[str] = ["/workspace", "/tmp/agent", "."]
    shell_blacklist: list[str] = [
        r"rm\s+-rf\s+/",
        r"\bmkfs\b",
        r"\bdd\s+if=",
        r">\s*/dev/sd",
    ]


class AnthropicSettings(BaseSettings):
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    timeout: int = 120
    planner_model: str = "claude-haiku-4-5"
    reflector_model: str = "claude-sonnet-4-6"


class SearchSettings(BaseSettings):
    provider: str = "tavily"
    tavily_api_key: str = ""
    brave_api_key: str = ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent: AgentSettings = AgentSettings()
    anthropic: AnthropicSettings = AnthropicSettings()
    search: SearchSettings = SearchSettings()
    skills: SkillsSettings = SkillsSettings()
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @classmethod
    def from_yaml(cls, config_path: Path | None = None) -> "Settings":
        path = config_path or Path(os.environ.get("CONFIG_PATH", str(_DEFAULT_CONFIG)))
        data: dict[str, Any] = {}
        if path.exists():
            data = _load_yaml(path)

        # Flatten nested yaml into field-compatible structure
        agent_data = data.get("agent", {})
        providers = data.get("providers", {})
        anthropic_data = providers.get("anthropic", {})
        anthropic_models = anthropic_data.get("models", {})
        search_data = data.get("search", {})
        skills_data = data.get("skills", {})

        return cls(
            log_level=data.get("log_level", "INFO"),
            agent=AgentSettings(
                name=agent_data.get("name", "Eve"),
                default_model=agent_data.get("default_model", "claude-haiku-4-5"),
                max_iterations=agent_data.get("max_iterations", 15),
                reflection_every=agent_data.get("reflection_every", 3),
                context_compression_threshold=agent_data.get(
                    "context_compression_threshold", 0.5
                ),
                workspace_paths=agent_data.get(
                    "workspace_paths", ["/workspace", "/tmp/agent", "."]
                ),
                shell_blacklist=agent_data.get("shell_blacklist", []),
            ),
            anthropic=AnthropicSettings(
                api_key=anthropic_data.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", ""),
                planner_model=anthropic_models.get("planner", "claude-haiku-4-5"),
                reflector_model=anthropic_models.get("reflector", "claude-sonnet-4-6"),
            ),
            search=SearchSettings(
                provider=search_data.get("provider", "tavily"),
                tavily_api_key=search_data.get("tavily_api_key") or os.environ.get("TAVILY_API_KEY", ""),
                brave_api_key=search_data.get("brave_api_key") or os.environ.get("BRAVE_API_KEY", ""),
            ),
            skills=SkillsSettings(
                skills_dir=skills_data.get("skills_dir", "core/src/agent/skills"),
                skills_drafts_dir=skills_data.get("skills_drafts_dir", "core/src/agent/skills/_drafts"),
                skills_auto_create=skills_data.get("skills_auto_create", True),
                skills_auto_create_threshold=skills_data.get("skills_auto_create_threshold", 3),
                skills_embedding_cache_dir=skills_data.get("skills_embedding_cache_dir", ".cache/skill_embeddings"),
                skills_match_k=skills_data.get("skills_match_k", 3),
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_yaml()
