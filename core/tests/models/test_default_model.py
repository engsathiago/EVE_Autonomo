"""
Testes para B.2: default_model = ollama_cloud:deepseek-v3.1:cloud.

Garante que:
- ModelSettings usa o novo default sem env vars
- from_yaml() propaga o default correto quando config.yaml não define models.default_model
- DEFAULT_MODEL env var sobrescreve o default
- config.yaml com models.default_model toma precedência sobre o hardcode
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.config import ModelSettings, Settings


def test_model_settings_default_is_ollama_cloud() -> None:
    """ModelSettings sem argumentos usa ollama_cloud como default."""
    s = ModelSettings()
    assert s.default_model == "ollama_cloud:deepseek-v3.1:cloud"


def test_from_yaml_default_without_models_section(tmp_path: Path) -> None:
    """from_yaml() com config.yaml sem seção 'models' usa o hardcode correto."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({"agent": {"name": "TestAgent"}}))

    with patch.dict(os.environ, {"DEFAULT_MODEL": ""}, clear=False):
        # Remove env var para forçar o fallback hardcoded
        env = {k: v for k, v in os.environ.items() if k != "DEFAULT_MODEL"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_yaml(cfg_file)

    assert settings.models.default_model == "ollama_cloud:deepseek-v3.1:cloud"


def test_env_var_overrides_default(tmp_path: Path) -> None:
    """DEFAULT_MODEL env var sobrescreve o hardcode."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({}))

    with patch.dict(os.environ, {"DEFAULT_MODEL": "anthropic:claude-haiku-4-5"}, clear=False):
        settings = Settings.from_yaml(cfg_file)

    assert settings.models.default_model == "anthropic:claude-haiku-4-5"


def test_yaml_models_section_takes_precedence(tmp_path: Path) -> None:
    """models.default_model no yaml toma precedência sobre env var."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump({"models": {"default_model": "openai:gpt-4o-mini"}})
    )

    with patch.dict(os.environ, {"DEFAULT_MODEL": "anthropic:claude-haiku-4-5"}, clear=False):
        settings = Settings.from_yaml(cfg_file)

    assert settings.models.default_model == "openai:gpt-4o-mini"
