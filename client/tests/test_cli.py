"""Tests for the CLI module."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from signal_light import cli
from signal_light import esp


def test_list_signals(capsys) -> None:
    result = cli.list_signals()
    captured = capsys.readouterr()

    assert result == 0
    assert "idle" in captured.out
    assert "working" in captured.out
    assert "blocked" in captured.out
    assert "permission" in captured.out


def test_play_signal_calls_esp(monkeypatch) -> None:
    mock_conn = MagicMock()
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "send_signal", lambda conn, sig, session_id="global": {"ok": True, "aggregate": "working"})

    result = cli.play_signal("working", session_id="test")

    assert result == 0


def test_play_signal_returns_error_on_connection_failure(monkeypatch) -> None:
    monkeypatch.setattr(esp, "get_connection", lambda: (_ for _ in ()).throw(esp.ESPConnectionError("no device")))

    result = cli.play_signal("working")

    assert result == 1


def test_show_status(monkeypatch, capsys) -> None:
    mock_conn = MagicMock()
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "get_status", lambda conn: {"aggregate": "idle", "sessions": {}})

    result = cli.show_status()
    captured = capsys.readouterr()

    assert result == 0
    data = json.loads(captured.out)
    assert data["aggregate"] == "idle"


def test_do_reset(monkeypatch, capsys) -> None:
    mock_conn = MagicMock()
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "reset", lambda conn: {"ok": True, "sessions_cleared": 3})

    result = cli.do_reset()
    captured = capsys.readouterr()

    assert result == 0
    assert "3 sessions cleared" in captured.out


def test_main_codex_hook(monkeypatch) -> None:
    calls = []
    mock_conn = MagicMock()
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "send_signal", lambda conn, sig, session_id="global": calls.append((sig, session_id)) or {"ok": True})
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"s1","event":"Stop"}'))

    result = cli.main(["codex-hook"])

    assert result == 0
    assert calls == [("turn_end", "s1")]


def test_main_claude_code_hook(monkeypatch) -> None:
    calls = []
    mock_conn = MagicMock()
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "send_signal", lambda conn, sig, session_id="global": calls.append((sig, session_id)) or {"ok": True})
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"cc1","event":"PermissionRequest"}'))

    result = cli.main(["claude-code-hook"])

    assert result == 0
    assert calls == [("permission", "cc1")]


def test_main_install_hooks(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "signal_light.hook_installer.run_install_wizard",
        lambda **kwargs: calls.append(kwargs) or 0,
    )

    result = cli.main(["install-hooks", "--agent", "codex", "--dry-run"])

    assert result == 0
    assert calls == [{"selected_agents": ["codex"], "all_agents": False, "yes": False, "dry_run": True}]


def test_main_no_command_prints_help(capsys) -> None:
    result = cli.main([])

    assert result == 2
