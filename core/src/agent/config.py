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
    # Default em produção aponta para volume writable fora do package read-only.
    # Override via env: SKILLS__SKILLS_DIR=/path/writable
    skills_dir: str = "/var/lib/agent/skills"
    skills_drafts_dir: str = "/var/lib/agent/skills/_drafts"
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


class OpenAISettings(BaseSettings):
    api_key: str = ""
    timeout: int = 120


class OpenRouterSettings(BaseSettings):
    api_key: str = ""
    http_referer: str = "https://github.com/agent"
    x_title: str = "agent"
    timeout: int = 120


class OllamaSettings(BaseSettings):
    base_url: str = "http://localhost:11434"
    api_key: str = ""  # opcional — necessário apenas para Ollama Cloud (ollama.com)
    timeout: int = 120


class OllamaCloudSettings(BaseSettings):
    base_url: str = "https://ollama.com"
    api_key: str = ""  # obrigatório para uso — transport valida na inicialização
    timeout: int = 120


class ModelSettings(BaseSettings):
    default_model: str = "ollama_cloud:deepseek-v3.1:cloud"
    fallback_chain: str = ""  # CSV: "ollama:qwen2.5:7b,anthropic:claude-haiku-4-5"
    timeout_s: int = 60

    def fallback_list(self) -> list[str]:
        return [m.strip() for m in self.fallback_chain.split(",") if m.strip()]


class RedisSettings(BaseSettings):
    url: str = "redis://redis:6379/0"


class ApprovalsSettings(BaseSettings):
    default_timeout_s: int = 1800  # 30 min
    scheduler_interval_s: int = 60


class OrchestratorSettings(BaseSettings):
    classifier_model: str = "ollama_cloud:gpt-oss:20b-cloud"
    classifier_max_tokens: int = 200
    fast_max_iterations: int = 3
    strategic_max_iterations: int = 8
    epic_max_parallel: int = 4
    epic_max_iterations_per_child: int = 6
    tier_cache_ttl_s: int = 300


class SchedulerSettings(BaseSettings):
    enabled: bool = True
    timezone: str = "America/Sao_Paulo"
    misfire_grace_seconds: int = 60
    max_instances: int = 3


class SubagentsSettings(BaseSettings):
    default_timeout_seconds: int = 120
    hard_timeout_seconds: int = 300
    max_concurrent_global: int = 8


class CriticSettings(BaseSettings):
    # Técnico e Advogado do Diabo usam modelo médio (3 chamadas LLM por avaliação)
    medium_model: str = "ollama_cloud:gpt-oss:20b-cloud"
    # Sintetizador usa modelo principal (decisão final)
    primary_model: str = "ollama_cloud:kimi-k2.5:cloud"
    cost_threshold_usd: float = 0.50
    enabled: bool = True


class MissionsSettings(BaseSettings):
    planner_model: str = "ollama_cloud:gpt-oss:20b-cloud"
    reflector_model: str = "ollama_cloud:kimi-k2.5:cloud"
    loop_interval_minutes: int = 5
    loop_enabled: bool = True


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
    openai: OpenAISettings = OpenAISettings()
    openrouter: OpenRouterSettings = OpenRouterSettings()
    ollama: OllamaSettings = OllamaSettings()
    ollama_cloud: OllamaCloudSettings = OllamaCloudSettings()
    models: ModelSettings = ModelSettings()
    search: SearchSettings = SearchSettings()
    skills: SkillsSettings = SkillsSettings()
    redis: RedisSettings = RedisSettings()
    approvals: ApprovalsSettings = ApprovalsSettings()
    orchestrator: OrchestratorSettings = OrchestratorSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    subagents: SubagentsSettings = SubagentsSettings()
    critic: CriticSettings = CriticSettings()
    missions: MissionsSettings = MissionsSettings()
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
        openai_data = providers.get("openai", {})
        openrouter_data = providers.get("openrouter", {})
        ollama_data = providers.get("ollama", {})
        ollama_cloud_data = providers.get("ollama_cloud", {})
        models_data = data.get("models", {})
        search_data = data.get("search", {})
        skills_data = data.get("skills", {})

        orchestrator_data = data.get("orchestrator", {})
        scheduler_data = data.get("scheduler", {})
        subagents_data = data.get("subagents", {})
        missions_data = data.get("missions", {})
        critic_data = data.get("critic", {})

        return cls(
            log_level=data.get("log_level", "INFO"),
            agent=AgentSettings(
                name=agent_data.get("name", "Eve"),
                default_model=agent_data.get("default_model", "claude-haiku-4-5"),
                max_iterations=agent_data.get("max_iterations", 15),
                reflection_every=agent_data.get("reflection_every", 3),
                context_compression_threshold=agent_data.get("context_compression_threshold", 0.5),
                workspace_paths=agent_data.get("workspace_paths", ["/workspace", "/tmp/agent", "."]),
                shell_blacklist=agent_data.get("shell_blacklist", []),
            ),
            anthropic=AnthropicSettings(
                api_key=anthropic_data.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", ""),
                planner_model=anthropic_models.get("planner", "claude-haiku-4-5"),
                reflector_model=anthropic_models.get("reflector", "claude-sonnet-4-6"),
            ),
            openai=OpenAISettings(
                api_key=openai_data.get("api_key") or os.environ.get("OPENAI_API_KEY", ""),
                timeout=openai_data.get("timeout", 120),
            ),
            openrouter=OpenRouterSettings(
                api_key=openrouter_data.get("api_key") or os.environ.get("OPENROUTER_API_KEY", ""),
                http_referer=openrouter_data.get("http_referer")
                or os.environ.get("OPENROUTER_HTTP_REFERER", "https://github.com/agent"),
                x_title=openrouter_data.get("x_title") or os.environ.get("OPENROUTER_X_TITLE", "agent"),
                timeout=openrouter_data.get("timeout", 120),
            ),
            ollama=OllamaSettings(
                base_url=ollama_data.get("base_url") or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                api_key=ollama_data.get("api_key") or os.environ.get("OLLAMA_API_KEY", ""),
                timeout=ollama_data.get("timeout", 120),
            ),
            ollama_cloud=OllamaCloudSettings(
                base_url=ollama_cloud_data.get("base_url") or os.environ.get("OLLAMA_CLOUD_BASE_URL", "https://ollama.com"),
                api_key=ollama_cloud_data.get("api_key") or os.environ.get("OLLAMA_CLOUD_API_KEY", ""),
                timeout=ollama_cloud_data.get("timeout", 120),
            ),
            models=ModelSettings(
                default_model=models_data.get("default_model")
                or os.environ.get("DEFAULT_MODEL", "ollama_cloud:deepseek-v3.1:cloud"),
                fallback_chain=models_data.get("fallback_chain") or os.environ.get("MODEL_FALLBACK_CHAIN", ""),
                timeout_s=int(models_data.get("timeout_s") or os.environ.get("MODEL_TIMEOUT_S", 60)),
            ),
            search=SearchSettings(
                provider=search_data.get("provider", "tavily"),
                tavily_api_key=search_data.get("tavily_api_key") or os.environ.get("TAVILY_API_KEY", ""),
                brave_api_key=search_data.get("brave_api_key") or os.environ.get("BRAVE_API_KEY", ""),
            ),
            skills=SkillsSettings(
                # Env var SKILLS__SKILLS_DIR toma precedência sobre docker-config.yaml.
                # Necessário porque docker-config.yaml é gerado no Dockerfile com path
                # que pode ser read-only em produção.
                skills_dir=(
                    os.environ.get("SKILLS__SKILLS_DIR") or skills_data.get("skills_dir", "/var/lib/agent/skills")
                ),
                skills_drafts_dir=(
                    os.environ.get("SKILLS__SKILLS_DRAFTS_DIR")
                    or skills_data.get("skills_drafts_dir", "/var/lib/agent/skills/_drafts")
                ),
                skills_auto_create=skills_data.get("skills_auto_create", True),
                skills_auto_create_threshold=skills_data.get("skills_auto_create_threshold", 3),
                skills_embedding_cache_dir=skills_data.get("skills_embedding_cache_dir", ".cache/skill_embeddings"),
                skills_match_k=skills_data.get("skills_match_k", 3),
            ),
            redis=RedisSettings(
                url=data.get("redis", {}).get("url") or os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            ),
            approvals=ApprovalsSettings(
                default_timeout_s=int(
                    data.get("approvals", {}).get("default_timeout_s")
                    or os.environ.get("APPROVAL_DEFAULT_TIMEOUT_SECONDS", 1800)
                ),
            ),
            orchestrator=OrchestratorSettings(
                classifier_model=orchestrator_data.get("classifier_model")
                or os.environ.get("ORCHESTRATOR_CLASSIFIER_MODEL", "ollama_cloud:gpt-oss:20b-cloud"),
                classifier_max_tokens=int(orchestrator_data.get("classifier_max_tokens", 200)),
                fast_max_iterations=int(orchestrator_data.get("fast_max_iterations", 3)),
                strategic_max_iterations=int(orchestrator_data.get("strategic_max_iterations", 8)),
                epic_max_parallel=int(orchestrator_data.get("epic_max_parallel", 4)),
                epic_max_iterations_per_child=int(orchestrator_data.get("epic_max_iterations_per_child", 6)),
                tier_cache_ttl_s=int(orchestrator_data.get("tier_cache_ttl_s", 300)),
            ),
            scheduler=SchedulerSettings(
                enabled=bool(scheduler_data.get("enabled", True)),
                timezone=scheduler_data.get("timezone") or os.environ.get("SCHEDULER_TZ", "America/Sao_Paulo"),
                misfire_grace_seconds=int(scheduler_data.get("misfire_grace_seconds", 60)),
                max_instances=int(scheduler_data.get("max_instances", 3)),
            ),
            subagents=SubagentsSettings(
                default_timeout_seconds=int(subagents_data.get("default_timeout_seconds", 120)),
                hard_timeout_seconds=int(subagents_data.get("hard_timeout_seconds", 300)),
                max_concurrent_global=int(subagents_data.get("max_concurrent_global", 8)),
            ),
            missions=MissionsSettings(
                planner_model=(
                    os.environ.get("MISSIONS_PLANNER_MODEL")
                    or missions_data.get("planner_model", "ollama_cloud:gpt-oss:20b-cloud")
                ),
                reflector_model=(
                    os.environ.get("MISSIONS_REFLECTOR_MODEL")
                    or missions_data.get("reflector_model", "ollama_cloud:kimi-k2.5:cloud")
                ),
                loop_interval_minutes=int(missions_data.get("loop_interval_minutes", 5)),
                loop_enabled=bool(missions_data.get("loop_enabled", True)),
            ),
            critic=CriticSettings(
                medium_model=(
                    os.environ.get("CRITIC__MEDIUM_MODEL")
                    or critic_data.get("medium_model", "ollama_cloud:gpt-oss:20b-cloud")
                ),
                primary_model=(
                    os.environ.get("CRITIC__PRIMARY_MODEL")
                    or critic_data.get("primary_model", "ollama_cloud:kimi-k2.5:cloud")
                ),
                cost_threshold_usd=float(critic_data.get("cost_threshold_usd", 0.50)),
                enabled=bool(critic_data.get("enabled", True)),
            ),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_yaml()


def build_model_router(
    settings: "Settings | None" = None,
    db_pool: Any | None = None,
) -> "Any":
    """Constrói e retorna um ModelRouter configurado com os providers disponíveis."""
    from agent.models.registry import TransportRegistry
    from agent.models.router import ModelRouter

    cfg = settings or get_settings()
    registry = TransportRegistry()

    # Anthropic — sempre registrado se tiver API key
    if cfg.anthropic.api_key:
        from agent.models.transports.anthropic import AnthropicTransport

        registry.register(
            "anthropic",
            lambda: AnthropicTransport(
                api_key=cfg.anthropic.api_key,
                base_url=cfg.anthropic.base_url,
                timeout=cfg.anthropic.timeout,
            ),
        )

    # OpenAI — registrado se tiver API key
    if cfg.openai.api_key:
        from agent.models.transports.openai import OpenAITransport

        registry.register(
            "openai",
            lambda: OpenAITransport(
                api_key=cfg.openai.api_key,
                timeout=cfg.openai.timeout,
            ),
        )

    # OpenRouter — registrado se tiver API key
    if cfg.openrouter.api_key:
        from agent.models.transports.openrouter import OpenRouterTransport

        registry.register(
            "openrouter",
            lambda: OpenRouterTransport(
                api_key=cfg.openrouter.api_key,
                http_referer=cfg.openrouter.http_referer,
                x_title=cfg.openrouter.x_title,
                timeout=cfg.openrouter.timeout,
            ),
        )

    # Ollama — sempre registrado (health check detecta se está rodando)
    from agent.models.transports.ollama import OllamaTransport

    registry.register(
        "ollama",
        lambda: OllamaTransport(
            base_url=cfg.ollama.base_url,
            api_key=cfg.ollama.api_key,
            timeout=cfg.ollama.timeout,
        ),
    )

    # Ollama Cloud — provider separado; registrado apenas quando api_key configurada
    if cfg.ollama_cloud.api_key:
        from agent.models.transports.ollama_cloud import OllamaCloudTransport

        _oc_cfg = cfg.ollama_cloud  # captura explícita para evitar closure sobre cfg mutável
        registry.register(
            "ollama_cloud",
            lambda: OllamaCloudTransport(
                base_url=_oc_cfg.base_url,
                api_key=_oc_cfg.api_key,
                timeout=_oc_cfg.timeout,
            ),
        )

    return ModelRouter(
        registry=registry,
        default_model=cfg.models.default_model,
        fallback_chain=cfg.models.fallback_list(),
        timeout_s=cfg.models.timeout_s,
        db_pool=db_pool,
    )
