"""
Testes para B.3: TierClassifier usa OrchestratorSettings.classifier_model.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.config import OrchestratorSettings, Settings
from agent.orchestrator.tiers import TierClassifier


def test_orchestrator_settings_default_is_ollama_cloud() -> None:
    s = OrchestratorSettings()
    assert s.classifier_model == "ollama_cloud:gpt-oss:20b-cloud"


def test_tier_classifier_default_matches_settings() -> None:
    """TierClassifier.__init__ default alinha com OrchestratorSettings default."""
    import inspect

    sig = inspect.signature(TierClassifier.__init__)
    assert sig.parameters["model"].default == "ollama_cloud:gpt-oss:20b-cloud"


def test_env_override_classifier_model(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({}))

    with patch.dict(
        os.environ,
        {"ORCHESTRATOR_CLASSIFIER_MODEL": "anthropic:claude-haiku-4-5"},
        clear=False,
    ):
        s = Settings.from_yaml(cfg_file)

    assert s.orchestrator.classifier_model == "anthropic:claude-haiku-4-5"


def test_yaml_orchestrator_section_takes_precedence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump({"orchestrator": {"classifier_model": "openai:gpt-4o-mini"}})
    )

    with patch.dict(
        os.environ,
        {"ORCHESTRATOR_CLASSIFIER_MODEL": "anthropic:claude-haiku-4-5"},
        clear=False,
    ):
        s = Settings.from_yaml(cfg_file)

    assert s.orchestrator.classifier_model == "openai:gpt-4o-mini"
