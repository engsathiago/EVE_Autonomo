import textwrap
from pathlib import Path

import pytest

from agent.config import _DEFAULT_CONFIG, Settings


def test_settings_from_yaml_loads_agent_name() -> None:
    s = Settings.from_yaml()
    assert s.agent.name == "Eve"


def test_settings_from_yaml_loads_models() -> None:
    s = Settings.from_yaml()
    assert "haiku" in s.agent.default_model


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # from_yaml() chama expandvars na hora — não usa o cache do get_settings()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    s = Settings.from_yaml()
    assert s.anthropic.api_key == "test-key-123"


def test_settings_workspace_paths_has_defaults() -> None:
    s = Settings.from_yaml()
    assert len(s.agent.workspace_paths) > 0


def test_settings_default_config_exists() -> None:
    assert _DEFAULT_CONFIG.exists(), f"config.yaml não encontrado em {_DEFAULT_CONFIG}"


def test_env_fallback_when_yaml_has_no_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Garante que os.environ é consultado quando o YAML não contém a api_key."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent("""\
            agent:
              name: "TestBot"
            providers:
              anthropic:
                models:
                  planner: "claude-haiku-4-5"
                  reflector: "claude-sonnet-4-6"
            search:
              provider: "tavily"
        """)
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fallback-anthropic-key")
    monkeypatch.setenv("TAVILY_API_KEY", "fallback-tavily-key")
    monkeypatch.setenv("BRAVE_API_KEY", "fallback-brave-key")

    s = Settings.from_yaml(cfg)

    assert s.anthropic.api_key == "fallback-anthropic-key"
    assert s.search.tavily_api_key == "fallback-tavily-key"
    assert s.search.brave_api_key == "fallback-brave-key"
