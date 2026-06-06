"""
Testes para B.3: MissionsSettings usa ollama_cloud como default.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from agent.config import MissionsSettings, Settings
from agent.missions.planner import MissionPlanner
from agent.missions.reflector import MissionReflector


def test_missions_settings_defaults_are_ollama_cloud() -> None:
    s = MissionsSettings()
    assert s.planner_model == "ollama_cloud:gpt-oss:20b-cloud"
    assert s.reflector_model == "ollama_cloud:kimi-k2.5:cloud"


def test_planner_and_reflector_defaults_match_settings() -> None:
    """__init__ defaults dos componentes alinham com MissionsSettings defaults."""
    import inspect

    planner_sig = inspect.signature(MissionPlanner.__init__)
    reflector_sig = inspect.signature(MissionReflector.__init__)
    assert planner_sig.parameters["model"].default == "ollama_cloud:gpt-oss:20b-cloud"
    assert reflector_sig.parameters["model"].default == "ollama_cloud:kimi-k2.5:cloud"


def test_env_override_missions_models(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump({}))

    with patch.dict(
        os.environ,
        {
            "MISSIONS_PLANNER_MODEL": "anthropic:claude-haiku-4-5",
            "MISSIONS_REFLECTOR_MODEL": "anthropic:claude-sonnet-4-6",
        },
        clear=False,
    ):
        s = Settings.from_yaml(cfg_file)

    assert s.missions.planner_model == "anthropic:claude-haiku-4-5"
    assert s.missions.reflector_model == "anthropic:claude-sonnet-4-6"


def test_yaml_missions_section_takes_precedence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump({
            "missions": {
                "planner_model": "openai:gpt-4o-mini",
                "reflector_model": "openai:gpt-4o",
            }
        })
    )

    with patch.dict(
        os.environ,
        {
            "MISSIONS_PLANNER_MODEL": "",
            "MISSIONS_REFLECTOR_MODEL": "",
        },
        clear=False,
    ):
        env = {k: v for k, v in os.environ.items()
               if k not in ("MISSIONS_PLANNER_MODEL", "MISSIONS_REFLECTOR_MODEL")}
        with patch.dict(os.environ, env, clear=True):
            s = Settings.from_yaml(cfg_file)

    assert s.missions.planner_model == "openai:gpt-4o-mini"
    assert s.missions.reflector_model == "openai:gpt-4o"
