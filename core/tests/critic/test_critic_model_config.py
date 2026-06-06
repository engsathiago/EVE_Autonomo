"""
Testes para B.3: Critic usa CriticSettings.medium_model / primary_model.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.config import CriticSettings, Settings
from agent.critic.critic import Critic


def test_critic_settings_defaults_are_ollama_cloud() -> None:
    s = CriticSettings()
    assert s.medium_model == "ollama_cloud:gpt-oss:20b-cloud"
    assert s.primary_model == "ollama_cloud:kimi-k2.5:cloud"


def test_critic_init_defaults_match_settings() -> None:
    """Critic.__init__ defaults alinham com CriticSettings defaults."""
    import inspect

    sig = inspect.signature(Critic.__init__)
    assert sig.parameters["medium_model"].default == "ollama_cloud:gpt-oss:20b-cloud"
    assert sig.parameters["primary_model"].default == "ollama_cloud:kimi-k2.5:cloud"


def test_env_override_critic_models(tmp_path: Path) -> None:
    """CRITIC__MEDIUM_MODEL e CRITIC__PRIMARY_MODEL sobrescrevem via pydantic __."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({}))

    with patch.dict(
        os.environ,
        {
            "CRITIC__MEDIUM_MODEL": "anthropic:claude-haiku-4-5",
            "CRITIC__PRIMARY_MODEL": "anthropic:claude-sonnet-4-6",
        },
        clear=False,
    ):
        s = Settings.from_yaml(cfg_file)

    assert s.critic.medium_model == "anthropic:claude-haiku-4-5"
    assert s.critic.primary_model == "anthropic:claude-sonnet-4-6"


def test_yaml_critic_section_takes_precedence(tmp_path: Path) -> None:
    """critic: block no yaml toma precedência sobre class defaults."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump({
            "critic": {
                "medium_model": "openai:gpt-4o-mini",
                "primary_model": "openai:gpt-4o",
            }
        })
    )

    s = Settings.from_yaml(cfg_file)

    assert s.critic.medium_model == "openai:gpt-4o-mini"
    assert s.critic.primary_model == "openai:gpt-4o"
