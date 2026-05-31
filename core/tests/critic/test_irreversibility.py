"""Testes unitários para agent.critic.irreversibility (D.4)."""

from agent.critic.irreversibility import is_irreversible


def test_read_file_safe():
    ok, reason = is_irreversible("read_file", {"path": "/tmp/x.txt"})
    assert ok is False
    assert reason == ""


def test_write_file_tmp_safe():
    ok, reason = is_irreversible("write_file", {"path": "/tmp/output.txt"})
    assert ok is False
    assert reason == ""


def test_write_file_home_irreversible():
    ok, reason = is_irreversible("write_file", {"path": "/home/user/data.txt"})
    assert ok is True
    assert "write_file" in reason


def test_shell_ls_safe():
    ok, reason = is_irreversible("shell", {"command": "ls -la /tmp"})
    assert ok is False
    assert reason == ""


def test_shell_rm_irreversible():
    ok, reason = is_irreversible("shell", {"command": "rm -rf /tmp/x"})
    assert ok is True
    assert "rm" in reason


def test_shell_git_push_irreversible():
    ok, reason = is_irreversible("shell", {"command": "git push origin main"})
    assert ok is True
    assert "git" in reason.lower() or "push" in reason.lower()


def test_send_telegram_irreversible():
    ok, reason = is_irreversible("send_telegram", {"chat_id": "123", "text": "hi"})
    assert ok is True
    assert "send_telegram" in reason


def test_unknown_tool_irreversible_failsafe():
    ok, reason = is_irreversible("super_tool_xyz", {})
    assert ok is True
    assert "desconhecida" in reason
