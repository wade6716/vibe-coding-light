"""Tests for signal_light.session_manager."""

import json
import time

from signal_light.session_manager import (
    SIGNAL_TO_PATTERN,
    SessionManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mgr(tmp_path):
    return SessionManager(state_file=tmp_path / "state.json")


# ---------------------------------------------------------------------------
# 1. Session CRUD
# ---------------------------------------------------------------------------

def test_handle_signal_upserts_session(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    status = mgr.get_status()
    assert "s1" in status["sessions"]
    assert status["sessions"]["s1"]["signal"] == "working"


def test_handle_signal_updates_existing_session(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "blocked")
    status = mgr.get_status()
    assert status["sessions"]["s1"]["signal"] == "blocked"


def test_handle_signal_removes_on_session_end(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "session_end")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]


def test_handle_signal_removes_on_off(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "off")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]


def test_handle_signal_session_done_marks_ended(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "session_done")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]
    assert "s1" in status["ended"]


# ---------------------------------------------------------------------------
# 2. Turn end logic
# ---------------------------------------------------------------------------

def test_turn_end_removes_non_urgent(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    result = mgr.handle_signal("s1", "turn_end")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]
    assert result.notice_first is True


def test_turn_end_keeps_urgent_permission(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "permission")
    result = mgr.handle_signal("s1", "turn_end")
    status = mgr.get_status()
    assert "s1" in status["sessions"]
    assert result.notice_first is False


def test_turn_end_keeps_urgent_blocked(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "blocked")
    mgr.handle_signal("s1", "turn_end")
    status = mgr.get_status()
    assert "s1" in status["sessions"]


def test_thinking_clears_ended_marker(tmp_path):
    """After turn_end, a new thinking signal (UserPromptSubmit) should
    clear the ended marker so the same session ID can start a new task."""
    mgr = _make_mgr(tmp_path)
    # First task
    mgr.handle_signal("s1", "working")
    r1 = mgr.handle_signal("s1", "turn_end")
    assert r1.pattern == "green_on"  # session removed, idle

    # tool_done after turn_end should be ignored (ended)
    r2 = mgr.handle_signal("s1", "tool_done")
    assert r2.pattern == "green_on"  # still idle

    # New task starts with thinking — should clear ended marker
    r3 = mgr.handle_signal("s1", "thinking")
    assert r3.pattern == "work_cycle"  # new task active!

    status = mgr.get_status()
    assert "s1" in status["sessions"]
    assert status["sessions"]["s1"]["signal"] == "thinking"


def test_turn_end_marks_ended_when_no_session(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("ghost", "turn_end")
    status = mgr.get_status()
    assert "ghost" not in status["sessions"]
    assert "ghost" in status["ended"]


# ---------------------------------------------------------------------------
# 3. Session start clears ended
# ---------------------------------------------------------------------------

def test_session_start_clears_ended(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "session_done")
    status = mgr.get_status()
    assert "s1" in status["ended"]

    mgr.handle_signal("s1", "session_start")
    status = mgr.get_status()
    assert "s1" in status["sessions"]
    assert "s1" not in status["ended"]


# ---------------------------------------------------------------------------
# 4. Ended session blocks stale signals
# ---------------------------------------------------------------------------

def test_ended_session_blocks_signal(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "session_done")
    mgr.handle_signal("s1", "working")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]


# ---------------------------------------------------------------------------
# 5. Aggregate priority
# ---------------------------------------------------------------------------

def test_aggregate_empty_is_idle(tmp_path):
    mgr = _make_mgr(tmp_path)
    status = mgr.get_status()
    assert status["aggregate"] == "idle"


def test_aggregate_single_working(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    status = mgr.get_status()
    assert status["aggregate"] == "working"


def test_aggregate_blocked_overrides_working(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s2", "blocked")
    status = mgr.get_status()
    assert status["aggregate"] == "blocked"


def test_aggregate_permission_overrides_attention(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "attention")
    mgr.handle_signal("s2", "permission")
    status = mgr.get_status()
    assert status["aggregate"] == "permission"


def test_aggregate_attention_overrides_working(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s2", "attention")
    status = mgr.get_status()
    assert status["aggregate"] == "attention"


# ---------------------------------------------------------------------------
# 6. Signal-to-pattern mapping
# ---------------------------------------------------------------------------

def test_signal_to_pattern_mapping():
    expected = {
        "idle": "green_on",
        "session_start": "green_on",
        "session_end": "green_on",
        "thinking": "work_cycle",
        "working": "work_cycle",
        "tool_done": "work_cycle",
        "attention": "flash_yellow",
        "permission": "flash_yellow",
        "done": "flash_yellow",
        "blocked": "flash_red",
        "session_done": "notice_green",
        "turn_end": "notice_green",
        "off": "off",
    }
    assert SIGNAL_TO_PATTERN == expected


def test_handle_signal_returns_correct_pattern(tmp_path):
    mgr = _make_mgr(tmp_path)
    result = mgr.handle_signal("s1", "blocked")
    assert result.pattern == "flash_red"


# ---------------------------------------------------------------------------
# 7. Notice first flag
# ---------------------------------------------------------------------------

def test_session_done_notice_first(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    result = mgr.handle_signal("s1", "session_done")
    assert result.notice_first is True


def test_turn_end_notice_first_for_non_urgent(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    result = mgr.handle_signal("s1", "turn_end")
    assert result.notice_first is True


def test_working_no_notice(tmp_path):
    mgr = _make_mgr(tmp_path)
    result = mgr.handle_signal("s1", "working")
    assert result.notice_first is False


def test_turn_end_no_notice_for_urgent(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "permission")
    result = mgr.handle_signal("s1", "turn_end")
    assert result.notice_first is False


# ---------------------------------------------------------------------------
# 8. Reset
# ---------------------------------------------------------------------------

def test_reset_clears_sessions(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s2", "blocked")
    mgr.reset()
    status = mgr.get_status()
    assert status["sessions"] == {}
    assert status["ended"] == {}


def test_reset_returns_count(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s2", "blocked")
    mgr.handle_signal("s3", "attention")
    count = mgr.reset()
    assert count == 3


# ---------------------------------------------------------------------------
# 9. TTL pruning
# ---------------------------------------------------------------------------

def test_expired_session_pruned(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")

    # Backdate the session's updated_at to 25 hours ago.
    state_file = tmp_path / "state.json"
    with open(state_file) as fp:
        data = json.load(fp)
    data["sessions"]["s1"]["updated_at"] = time.time() - 25 * 3600
    with open(state_file, "w") as fp:
        json.dump(data, fp)

    # Next call triggers pruning.
    mgr.handle_signal("s2", "working")
    status = mgr.get_status()
    assert "s1" not in status["sessions"]


def test_expired_ended_pruned(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.handle_signal("s1", "working")
    mgr.handle_signal("s1", "session_done")

    # Backdate the ended marker to 11 minutes ago.
    state_file = tmp_path / "state.json"
    with open(state_file) as fp:
        data = json.load(fp)
    data["ended"]["s1"]["removed_at"] = time.time() - 11 * 60
    with open(state_file, "w") as fp:
        json.dump(data, fp)

    # Next call triggers pruning.
    mgr.handle_signal("s2", "working")
    status = mgr.get_status()
    assert "s1" not in status["ended"]
