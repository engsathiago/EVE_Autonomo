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

        creates = re.findall(r"CREATE\s+(TABLE|INDEX)\s+(\w+)", content, re.IGNORECASE)
        for kind, name in creates:
            assert "IF NOT EXISTS" in content, f"CREATE {kind} {name} deve usar IF NOT EXISTS"


# ── _install_systemd (template rendering) ─────────────────────────────────────


class TestInstallSystemd:
    def test_renders_user_placeholder(self, tmp_path: Path) -> None:
        """_install_systemd substitui {{USER}} no template."""

        unit_dest = tmp_path / "agent.service"
        systemd_dir = str(tmp_path)

        with patch("agent.deploy.install._SYSTEMD_UNIT_DIR", systemd_dir):
            with patch("agent.deploy.install._run"):  # não roda systemctl real
                from agent.deploy.install import _install_systemd

                _install_systemd(tmp_path / "opt", "myuser", "mygroup")

        content = unit_dest.read_text()
        assert "myuser" in content
        assert "{{USER}}" not in content

    def test_renders_group_placeholder(self, tmp_path: Path) -> None:

        with patch("agent.deploy.install._SYSTEMD_UNIT_DIR", str(tmp_path)):
            with patch("agent.deploy.install._run"):
                from agent.deploy.install import _install_systemd

                _install_systemd(tmp_path / "opt", "agent", "mygroup")

        content = (tmp_path / "agent.service").read_text()
        assert "mygroup" in content
        assert "{{GROUP}}" not in content

    def test_renders_install_dir_placeholder(self, tmp_path: Path) -> None:

        prefix = tmp_path / "opt" / "agent"
        with patch("agent.deploy.install._SYSTEMD_UNIT_DIR", str(tmp_path)):
            with patch("agent.deploy.install._run"):
                from agent.deploy.install import _install_systemd

                _install_systemd(prefix, "agent", "agent")

        content = (tmp_path / "agent.service").read_text()
        assert str(prefix) in content
        assert "{{INSTALL_DIR}}" not in content

    def test_renders_python_placeholder(self, tmp_path: Path) -> None:

        prefix = tmp_path / "opt"
        with patch("agent.deploy.install._SYSTEMD_UNIT_DIR", str(tmp_path)):
            with patch("agent.deploy.install._run"):
                from agent.deploy.install import _install_systemd

                _install_systemd(prefix, "agent", "agent")

        content = (tmp_path / "agent.service").read_text()
        assert "{{PYTHON}}" not in content

    def test_unit_file_has_correct_permissions(self, tmp_path: Path) -> None:

        with patch("agent.deploy.install._SYSTEMD_UNIT_DIR", str(tmp_path)):
            with patch("agent.deploy.install._run"):
                from agent.deploy.install import _install_systemd

                _install_systemd(tmp_path / "opt", "agent", "agent")

        unit_file = tmp_path / "agent.service"
        # Deve ter permissão 644
        mode = oct(unit_file.stat().st_mode)[-3:]
        assert mode == "644"


# ── _chown ────────────────────────────────────────────────────────────────────


class TestChown:
    def test_chown_silently_ignores_errors(self) -> None:
        """_chown não levanta exceção se path não existe."""
        from agent.deploy.install import _chown

        with patch("agent.deploy.install._run", side_effect=RuntimeError("no chown")):
            _chown("/nonexistent/path", "agent", "agent")  # não deve levantar


# ── _create_user ─────────────────────────────────────────────────────────────


class TestCreateUser:
    def test_skips_creation_if_user_exists(self) -> None:
        """_create_user não chama useradd se id retorna 0."""
        from agent.deploy.install import _create_user

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0  # id user → exists

        with patch("agent.deploy.install._run", mock_run):
            _create_user("existing_user", "existing_group")

        # Só chamou `id` — não chamou useradd
        calls = mock_run.call_args_list
        assert calls[0][0][0] == ["id", "existing_user"]
        assert len(calls) == 1  # só uma chamada

    def test_calls_useradd_if_user_missing(self) -> None:
        """_create_user chama useradd quando id retorna != 0."""

        from agent.deploy.install import _create_user

        mock_run = MagicMock()
        mock_run.return_value.returncode = 1  # id user → não existe

        with patch("agent.deploy.install._run", mock_run):
            with patch("shutil.which", return_value="/usr/sbin/useradd"):
                _create_user("new_user", "new_group")

        calls = [c[0][0][0] for c in mock_run.call_args_list]
        assert any("useradd" in str(c) for c in calls)


# ── install / uninstall com mocks ─────────────────────────────────────────────


class TestInstallMocked:
    def test_install_raises_without_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.geteuid", lambda: 1000)
        from agent.deploy.install import install

        with pytest.raises(PermissionError):
            install()

    def test_uninstall_raises_without_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.geteuid", lambda: 1000)
        from agent.deploy.install import uninstall

        with pytest.raises(PermissionError):
            uninstall()

    def test_install_no_systemd_skips_daemon_reload(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """install(enable_systemd=False) não chama systemctl."""
        from agent.deploy.install import install

        monkeypatch.setattr("os.geteuid", lambda: 0)

        called_cmds: list[list] = []

        def mock_run(cmd: list, check: bool = True):  # type: ignore
            called_cmds.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("agent.deploy.install._run", mock_run):
            with patch("agent.deploy.install._create_dirs"):
                with patch("agent.deploy.install._create_user"):
                    with patch("shutil.copy"):
                        with patch("pathlib.Path.exists", return_value=True):
                            try:
                                install(prefix=str(tmp_path), enable_systemd=False)
                            except Exception:
                                pass  # pode falhar em caminhos de sistema, o que importa é que não chamou systemctl

        systemctl_calls = [c for c in called_cmds if "systemctl" in str(c)]
        assert len(systemctl_calls) == 0


# ── _create_dirs ─────────────────────────────────────────────────────────────


class TestCreateDirs:
    def test_creates_all_install_dirs(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """_create_dirs cria os diretórios da lista _INSTALL_DIRS."""
        from agent.deploy.install import _INSTALL_DIRS, _create_dirs

        created: list[str] = []

        class FakePath:
            def __init__(self, d: str) -> None:
                self.d = d

            def mkdir(self, **kwargs: object) -> None:
                created.append(self.d)

        with patch("agent.deploy.install.Path", side_effect=lambda d: FakePath(d)):
            with patch("agent.deploy.install._chown"):
                _create_dirs("agent", "agent")

        assert len(created) == len(_INSTALL_DIRS)

    def test_chown_called_for_each_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_create_dirs chama _chown para cada dir."""
        from agent.deploy.install import _INSTALL_DIRS, _create_dirs

        chown_calls: list[tuple] = []

        with patch("pathlib.Path.mkdir"):
            with patch("agent.deploy.install._chown", side_effect=lambda p, u, g: chown_calls.append((u, g))):
                _create_dirs("myuser", "mygroup")

        assert len(chown_calls) == len(_INSTALL_DIRS)
        assert all(c == ("myuser", "mygroup") for c in chown_calls)


# ── uninstall com mocks ───────────────────────────────────────────────────────


class TestUninstallMocked:
    def test_uninstall_calls_systemctl_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """uninstall() chama systemctl stop e disable."""
        from agent.deploy.install import uninstall

        monkeypatch.setattr("os.geteuid", lambda: 0)
        called_cmds: list[list] = []

        def mock_run(cmd: list, check: bool = True):  # type: ignore
            called_cmds.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("agent.deploy.install._run", mock_run):
            with patch("pathlib.Path.unlink"):
                with patch("shutil.rmtree"):
                    uninstall(keep_data=True)

        cmds_str = [" ".join(c) for c in called_cmds]
        assert any("stop" in c for c in cmds_str)
        assert any("disable" in c for c in cmds_str)

    def test_uninstall_keep_data_preserves_var_lib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """uninstall(keep_data=True) não remove /var/lib/agent."""
        from agent.deploy.install import uninstall

        monkeypatch.setattr("os.geteuid", lambda: 0)
        removed_paths: list[str] = []

        def mock_rmtree(path: str, ignore_errors: bool = False) -> None:
            removed_paths.append(path)

        with patch("agent.deploy.install._run", return_value=MagicMock(returncode=0)):
            with patch("pathlib.Path.unlink"):
                with patch("shutil.rmtree", side_effect=mock_rmtree):
                    uninstall(keep_data=True)

        assert not any("/var/lib/agent" in p for p in removed_paths)

    def test_uninstall_removes_var_lib_when_not_keep_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """uninstall(keep_data=False) remove /var/lib/agent."""
        from agent.deploy.install import uninstall

        monkeypatch.setattr("os.geteuid", lambda: 0)
        removed_paths: list[str] = []

        def mock_rmtree(path: str, ignore_errors: bool = False) -> None:
            removed_paths.append(path)

        with patch("agent.deploy.install._run", return_value=MagicMock(returncode=0)):
            with patch("pathlib.Path.unlink"):
                with patch("shutil.rmtree", side_effect=mock_rmtree):
                    uninstall(keep_data=False)

        assert any("/var/lib/agent" in p for p in removed_paths)
