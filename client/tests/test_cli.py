"""Tests for the CLI module."""

import io
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from signal_light import cli
from signal_light import esp
from signal_light.session_manager import SignalResult


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
    mock_result = SignalResult(pattern="work_cycle", notice_first=False)

    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.handle_signal",
        lambda self, sid, sig: mock_result,
    )
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)

    send_calls = []
    monkeypatch.setattr(
        esp, "send_pattern",
        lambda conn, pattern, timeout=None: send_calls.append({"pattern": pattern, "timeout": timeout}),
    )

    result = cli.play_signal("working", session_id="test")

    assert result == 0
    assert len(send_calls) == 1
    assert send_calls[0]["pattern"] == "work_cycle"
    assert send_calls[0]["timeout"] == 300


def test_play_signal_returns_error_on_connection_failure(monkeypatch) -> None:
    mock_result = SignalResult(pattern="work_cycle", notice_first=False)
    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.handle_signal",
        lambda self, sid, sig: mock_result,
    )
    monkeypatch.setattr(esp, "get_connection", lambda: (_ for _ in ()).throw(esp.ESPConnectionError("no device")))

    result = cli.play_signal("working")

    assert result == 1


def test_show_status(monkeypatch, capsys) -> None:
    mock_conn = MagicMock()
    mock_mgr_status = {
        "sessions": {"s1": {"signal": "working", "category": "working"}},
        "ended": {},
        "aggregate": "working",
    }

    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.get_status",
        lambda self: mock_mgr_status,
    )
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "get_status", lambda conn: {"pattern": "work_cycle", "leds": {"red": False, "yellow": False, "green": True}})

    result = cli.show_status()
    captured = capsys.readouterr()

    assert result == 0
    data = json.loads(captured.out)
    assert data["aggregate"] == "working"
    assert "sessions" in data
    assert data["esp"]["pattern"] == "work_cycle"


def test_do_reset(monkeypatch, capsys) -> None:
    mock_conn = MagicMock()
    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.reset",
        lambda self: 3,
    )
    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)
    monkeypatch.setattr(esp, "reset", lambda conn: {"ok": True})

    result = cli.do_reset()
    captured = capsys.readouterr()

    assert result == 0
    assert "Reset: 3 sessions cleared" in captured.out


def test_main_codex_hook(monkeypatch) -> None:
    mock_result = SignalResult(pattern="notice_green", notice_first=False)
    mock_conn = MagicMock()

    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)

    send_calls = []
    monkeypatch.setattr(
        esp, "send_pattern",
        lambda conn, pattern, timeout=None: send_calls.append({"pattern": pattern, "timeout": timeout}),
    )
    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.handle_signal",
        lambda self, sid, sig: mock_result,
    )
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"s1","event":"Stop"}'))

    result = cli.main(["codex-hook"])

    assert result == 0
    assert len(send_calls) >= 1
    # The final call should carry the pattern from handle_signal
    assert send_calls[-1]["pattern"] == "notice_green"


def test_main_claude_code_hook(monkeypatch) -> None:
    mock_result = SignalResult(pattern="flash_yellow", notice_first=False)
    mock_conn = MagicMock()

    monkeypatch.setattr(esp, "get_connection", lambda: mock_conn)

    send_calls = []
    monkeypatch.setattr(
        esp, "send_pattern",
        lambda conn, pattern, timeout=None: send_calls.append({"pattern": pattern, "timeout": timeout}),
    )
    monkeypatch.setattr(
        "signal_light.session_manager.SessionManager.handle_signal",
        lambda self, sid, sig: mock_result,
    )
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":"cc1","event":"PermissionRequest"}'))

    result = cli.main(["claude-code-hook"])

    assert result == 0
    assert len(send_calls) >= 1
    assert send_calls[-1]["pattern"] == "flash_yellow"


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
