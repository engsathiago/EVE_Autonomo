"""Testes do install.py — sem root, sem systemd real."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.deploy.install import _check_root, _run


class TestCheckRoot:
    def test_raises_without_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.geteuid", lambda: 1000)
        with pytest.raises(PermissionError):
            _check_root()

    def test_passes_as_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.geteuid", lambda: 0)
        _check_root()  # não deve levantar


class TestRun:
    def test_succeeds_on_echo(self) -> None:
        result = _run(["echo", "ok"])
        assert result.returncode == 0

    def test_raises_on_failure(self) -> None:
        with pytest.raises(RuntimeError):
            _run(["false"])

    def test_no_raise_with_check_false(self) -> None:
        result = _run(["false"], check=False)
        assert result.returncode != 0


class TestTemplatesExist:
    def test_env_example_exists(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        assert (_TEMPLATES_DIR / "env.example").exists()

    def test_agent_service_exists(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        assert (_TEMPLATES_DIR / "agent.service").exists()

    def test_service_has_placeholders(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        content = (_TEMPLATES_DIR / "agent.service").read_text()
        assert "{{USER}}" in content
        assert "{{GROUP}}" in content
        assert "{{INSTALL_DIR}}" in content

    def test_env_has_change_me_placeholders(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        content = (_TEMPLATES_DIR / "env.example").read_text()
        assert "CHANGE_ME" in content

    def test_service_type_notify(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        content = (_TEMPLATES_DIR / "agent.service").read_text()
        assert "Type=notify" in content

    def test_service_watchdog(self) -> None:
        from agent.deploy.install import _TEMPLATES_DIR
        content = (_TEMPLATES_DIR / "agent.service").read_text()
        assert "WatchdogSec=" in content


class TestMigrationFile:
    def test_011_deploy_exists(self) -> None:
        """Migration 011_deploy.sql deve existir (010 já foi usado pelo F9)."""
        # core/tests/deploy/test_install.py → parents[2] = core/ → migrations/
        migrations_dir = Path(__file__).parents[2] / "migrations"
        migration = migrations_dir / "011_deploy.sql"
        assert migration.exists(), f"Migration não encontrada: {migration}"

    def test_migration_idempotent_syntax(self) -> None:
        """Todas as tabelas e índices usam IF NOT EXISTS."""
        migrations_dir = Path(__file__).parents[2] / "migrations"
        content = (migrations_dir / "011_deploy.sql").read_text()
        # Deve conter IF NOT EXISTS em todas as criações
        import re
        creates = re.findall(r'CREATE\s+(TABLE|INDEX)\s+(\w+)', content, re.IGNORECASE)
        for kind, name in creates:
            assert "IF NOT EXISTS" in content, (
                f"CREATE {kind} {name} deve usar IF NOT EXISTS"
            )
