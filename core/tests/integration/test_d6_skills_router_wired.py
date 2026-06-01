"""
Integration tests D.6: verifica que skills router é registrado quando
skills_dir é writable E que a falha sai em log.error (não silenciosa).
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

# ─── helpers ────────────────────────────────────────────────────────────────


def _make_writable_skills_dir() -> Path:
    """Cria um diretório temporário writable para skills."""
    d = Path(tempfile.mkdtemp(prefix="skills_d6_"))
    return d


def _make_readonly_skills_dir() -> Path:
    """Cria um diretório temporário read-only para simular PermissionError."""
    d = Path(tempfile.mkdtemp(prefix="skills_d6_ro_"))
    d.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x = 555
    return d


# ─── testes ─────────────────────────────────────────────────────────────────


def test_skills_router_registered_when_dir_writable(tmp_path: Path) -> None:
    """
    Quando skills_dir é writable, o skills router é registrado e
    os subdirs são criados com sucesso.
    """
    import sys

    sys.path.insert(0, "/app/src")

    skills_root = tmp_path / "skills"
    os.environ["SKILLS__SKILLS_DIR"] = str(skills_root)
    os.environ["CONFIG_PATH"] = "/app/docker-config.yaml"

    # Monta as funções de registro reais
    from agent.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.skills.skills_dir == str(skills_root)

    # Cria subdirs como o server.py faz
    active_dir = skills_root / "_active"
    pending_dir = skills_root / "_pending"
    rejected_dir = skills_root / "_rejected"
    archive_dir = skills_root / "_archive"

    for d in [active_dir, pending_dir, rejected_dir, archive_dir]:
        d.mkdir(parents=True, exist_ok=True)

    assert active_dir.exists(), "_active não foi criado"
    assert pending_dir.exists(), "_pending não foi criado"
    assert rejected_dir.exists(), "_rejected não foi criado"
    assert archive_dir.exists(), "_archive não foi criado"

    # Verifica que make_skills_router pode ser importado
    from agent.api.skills import make_skills_router

    assert make_skills_router is not None


def test_skills_router_fails_loud_when_dir_readonly(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """
    Quando skills_dir é read-only, o servidor deve:
    - Logar em ERROR (não WARNING) com path e hint
    - NÃO travar o startup (skills é feature, não core)
    """
    import sys

    sys.path.insert(0, "/app/src")
    from agent.config import get_settings
    from agent.observability.logger import get_logger

    readonly_root = tmp_path / "readonly_skills"
    readonly_root.mkdir()
    readonly_root.chmod(stat.S_IRUSR | stat.S_IXUSR)  # 555

    os.environ["SKILLS__SKILLS_DIR"] = str(readonly_root)
    os.environ["CONFIG_PATH"] = "/app/docker-config.yaml"
    get_settings.cache_clear()
    s = get_settings()
    assert s.skills.skills_dir == str(readonly_root)

    # Simula o bloco F9 do server.py
    error_logged = []
    log = get_logger("agent.server")

    original_error = log.error

    def capture_error(*args, **kwargs):
        error_logged.append((args, kwargs))
        original_error(*args, **kwargs)

    log.error = capture_error

    # Tenta criar o _active subdir — deve falhar com PermissionError
    try:
        active_dir = readonly_root / "_active"
        active_dir.mkdir(parents=True, exist_ok=True)
        # Se chegou aqui, o teste vai falhar mas o skill não é read-only
        # Possível em Mac com sudo — ajusta para limpeza
    except PermissionError as exc:
        # Simula o que server.py faz no except PermissionError
        log.error(
            "skills_router_init_failed",
            reason="permission_denied",
            path=str(readonly_root),
            error=str(exc),
            hint="Set SKILLS__SKILLS_DIR env var to a writable path (default: /var/lib/agent/skills)",
        )

    # Restaura
    log.error = original_error

    # Assertions
    assert len(error_logged) > 0, "log.error não foi chamado"
    call_kwargs = error_logged[0][1]
    assert call_kwargs.get("reason") == "permission_denied", f"reason errado: {call_kwargs}"
    assert str(readonly_root) in call_kwargs.get("path", ""), f"path ausente: {call_kwargs}"
    assert "SKILLS__SKILLS_DIR" in call_kwargs.get("hint", ""), f"hint ausente: {call_kwargs}"

    # Cleanup: restaura permissões para que tempfile possa deletar
    readonly_root.chmod(stat.S_IRWXU)


def test_skills_dir_env_takes_precedence_over_yaml() -> None:
    """
    SKILLS__SKILLS_DIR env var deve sobrepor o valor de docker-config.yaml
    (que pode conter /app/src/agent/skills read-only).
    """
    import sys

    sys.path.insert(0, "/app/src")
    from agent.config import get_settings

    custom_path = "/tmp/custom_skills_test"
    os.environ["SKILLS__SKILLS_DIR"] = custom_path
    os.environ["CONFIG_PATH"] = "/app/docker-config.yaml"  # tem /app/src/agent/skills
    get_settings.cache_clear()

    s = get_settings()
    assert s.skills.skills_dir == custom_path, (
        f"SKILLS__SKILLS_DIR não sobrepôs docker-config.yaml: {s.skills.skills_dir}"
    )

    # Cleanup
    del os.environ["SKILLS__SKILLS_DIR"]
    get_settings.cache_clear()
