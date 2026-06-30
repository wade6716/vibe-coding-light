"""Tests for agent signal definitions and hook adapters."""

import io
import json
import os
from pathlib import Path

import pytest

from signal_light.agent_signals import SIGNALS
from signal_light.codex_hook import CodexHookInput, choose_signal, session_key
from signal_light.claude_code_hook import ClaudeCodeHookInput, choose_signal as cc_choose_signal


class RecordingLight:
    def __init__(self) -> None:
        self.states: list[tuple[bool, bool, bool]] = []
        self.brightness_states: list[tuple[float, float, float]] = []

    def write(self, *, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        self.states.append((green, yellow, red))

    def write_brightness(self, *, green: float = 0.0, yellow: float = 0.0, red: float = 0.0) -> None:
        self.brightness_states.append((green, yellow, red))

    def off(self) -> None:
        self.write()


def test_idle_signal_leaves_green_on() -> None:
    light = RecordingLight()
    SIGNALS["idle"].play(light, speed=0.05)
    assert SIGNALS["idle"].repeat is False
    assert light.states[-1] == (True, False, False)


def test_working_signal_uses_soft_green_yellow_red_cycle() -> None:
    light = RecordingLight()
    SIGNALS["working"].play(light, speed=0.05, cycles=1)
    assert SIGNALS["working"].repeat is True
    assert len(light.brightness_states) == 27
    assert all(green > 0 and yellow == 0 and red == 0 for green, yellow, red in light.brightness_states[:9])
    assert all(green == 0 and yellow > 0 and red == 0 for green, yellow, red in light.brightness_states[9:18])
    assert all(green == 0 and yellow == 0 and red > 0 for green, yellow, red in light.brightness_states[18:27])


def test_attention_signal_flashes_yellow() -> None:
    light = RecordingLight()
    SIGNALS["attention"].play(light, speed=0.05, cycles=1)
    assert SIGNALS["attention"].repeat is True
    assert light.states[:2] == [(False, True, False), (False, False, False)]


def test_permission_signal_flashes_yellow() -> None:
    light = RecordingLight()
    SIGNALS["permission"].play(light, speed=0.05, cycles=1)
    assert SIGNALS["permission"].repeat is True
    assert light.states[:2] == [(False, True, False), (False, False, False)]


def test_session_end_returns_to_idle_green() -> None:
    light = RecordingLight()
    SIGNALS["session_end"].play(light, speed=0.05)
    assert light.states[-1] == (True, False, False)


def test_codex_stop_maps_to_turn_end() -> None:
    signal = choose_signal(CodexHookInput(event_name="Stop", payload={}))
    assert signal == "turn_end"


def test_failed_payload_maps_to_blocked() -> None:
    signal = choose_signal(CodexHookInput(event_name="PostToolUse", payload={"status": "failed"}))
    assert signal == "blocked"


def test_success_status_does_not_become_unknown_signal() -> None:
    signal = choose_signal(CodexHookInput(event_name="PostToolUse", payload={"status": "success"}))
    assert signal == "tool_done"


def test_claude_code_notification_maps_to_attention() -> None:
    signal = cc_choose_signal(ClaudeCodeHookInput(event_name="Notification", payload={}))
    assert signal == "attention"


def test_claude_code_permission_maps_to_permission() -> None:
    signal = cc_choose_signal(ClaudeCodeHookInput(event_name="PermissionRequest", payload={}))
    assert signal == "permission"


def test_claude_code_stop_maps_to_turn_end() -> None:
    signal = cc_choose_signal(ClaudeCodeHookInput(event_name="Stop", payload={}))
    assert signal == "turn_end"


def test_claude_code_stop_reason_error_maps_to_blocked() -> None:
    signal = cc_choose_signal(ClaudeCodeHookInput(event_name="Stop", payload={"stop_reason": "error"}))
    assert signal == "blocked"


def test_session_key_prefers_payload_session_id() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={"session_id": "session-a", "cwd": "/tmp/x"}),
        {},
    )
    assert key == "session-a"


def test_session_key_falls_back_to_cwd() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={"cwd": "/tmp/project"}),
        {},
    )
    assert key == "cwd:/tmp/project"


def test_codex_session_key_prefers_env() -> None:
    key = session_key(
        CodexHookInput(event_name="Stop", payload={}),
        {"CODEX_SESSION_ID": "env-session"},
    )
    assert key == "env-session"


def test_claude_session_key_prefers_payload() -> None:
    from signal_light.claude_code_hook import session_key as cc_session_key

    key = cc_session_key(
        ClaudeCodeHookInput(event_name="Stop", payload={"session_id": "cc-session"}),
        {},
    )
    assert key == "cc-session"


def test_antigravity_read_hook_input_from_args() -> None:
    from signal_light.antigravity_hook import read_hook_input
    hook_input = read_hook_input(["signal-light", "--event", "PreToolUse"], "{}")
    assert hook_input.event_name == "PreToolUse"
    assert hook_input.payload == {}


def test_antigravity_read_hook_input_fallback_pre_tool_use() -> None:
    from signal_light.antigravity_hook import read_hook_input
    # 根据 toolCall 字段推断为 PreToolUse
    hook_input = read_hook_input(["signal-light"], '{"toolCall": {"name": "run_command"}}')
    assert hook_input.event_name == "PreToolUse"


def test_antigravity_read_hook_input_fallback_post_tool_use() -> None:
    from signal_light.antigravity_hook import read_hook_input
    # 根据 error/stepIdx 字段推断为 PostToolUse
    hook_input = read_hook_input(["signal-light"], '{"stepIdx": 5, "error": ""}')
    assert hook_input.event_name == "PostToolUse"


def test_antigravity_choose_signal_pre_tool_use_normal() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    # 普通工具调用，信号为 working
    sig = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "view_file"}}))
    assert sig == "working"


def test_antigravity_choose_signal_pre_tool_use_run_command() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    # run_command 工具调用，信号为 permission
    sig = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "run_command"}}))
    assert sig == "permission"


def test_antigravity_choose_signal_pre_tool_use_permission() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    # ask_permission 工具调用，信号为 permission
    sig = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "ask_permission"}}))
    assert sig == "permission"
    sig2 = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "default_api:ask_permission"}}))
    assert sig2 == "permission"


def test_antigravity_choose_signal_pre_tool_use_question() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    # ask_question 工具调用，信号为 attention
    sig = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "ask_question"}}))
    assert sig == "attention"
    sig2 = choose_signal(AntigravityHookInput(event_name="PreToolUse", payload={"toolCall": {"name": "default_api:ask_question"}}))
    assert sig2 == "attention"


def test_antigravity_choose_signal_post_tool_use_success() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    sig = choose_signal(AntigravityHookInput(event_name="PostToolUse", payload={"error": ""}))
    assert sig == "tool_done"


def test_antigravity_choose_signal_post_tool_use_error() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    sig = choose_signal(AntigravityHookInput(event_name="PostToolUse", payload={"error": "some command failure"}))
    assert sig == "blocked"


def test_antigravity_choose_signal_stop_idle() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    sig = choose_signal(AntigravityHookInput(event_name="Stop", payload={"fullyIdle": True}))
    assert sig == "session_done"


def test_antigravity_choose_signal_stop_not_idle() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    sig = choose_signal(AntigravityHookInput(event_name="Stop", payload={"fullyIdle": False}))
    assert sig == "turn_end"


def test_antigravity_choose_signal_stop_error() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, choose_signal
    sig = choose_signal(AntigravityHookInput(event_name="Stop", payload={"error": "system crash"}))
    assert sig == "blocked"


def test_antigravity_session_key_prefers_conversation_id() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, session_key
    key = session_key(AntigravityHookInput(event_name="PreToolUse", payload={"conversationId": "conv-123"}), {})
    assert key == "conv-123"


def test_antigravity_session_key_falls_back_to_workspace() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, session_key
    key = session_key(AntigravityHookInput(event_name="PreToolUse", payload={"workspacePaths": ["/home/user/my-proj"]}), {})
    assert key == "workspace:/home/user/my-proj"


def test_antigravity_process_and_get_output() -> None:
    from signal_light.antigravity_hook import AntigravityHookInput, process_and_get_output
    assert process_and_get_output(AntigravityHookInput(event_name="PreToolUse", payload={})) == {"decision": "allow"}
    assert process_and_get_output(AntigravityHookInput(event_name="PostToolUse", payload={})) == {}
    assert process_and_get_output(AntigravityHookInput(event_name="PreInvocation", payload={})) == {"injectSteps": []}
    assert process_and_get_output(AntigravityHookInput(event_name="PostInvocation", payload={})) == {"injectSteps": [], "terminationBehavior": ""}
    assert process_and_get_output(AntigravityHookInput(event_name="Stop", payload={})) == {"decision": "allow"}


def test_hook_installer_antigravity_spec() -> None:
    from pathlib import Path
    from signal_light.hook_installer import supported_agents
    
    agents = supported_agents(Path("/dummy/home"))
    assert "antigravity" in agents
    spec = agents["antigravity"]
    assert spec.root_key == "signal-light"
    assert spec.config_path == Path("/dummy/home/.gemini/config/hooks.json")
    assert spec.uses_matcher is True


def test_hook_installer_antigravity_event_merging() -> None:
    from pathlib import Path
    from signal_light.hook_installer import supported_agents, _event_has_expected_hook, _merge_event_groups
    
    spec = supported_agents(Path("/dummy/home"))["antigravity"]
    
    # 1. 嵌套事件 PreToolUse (uses matcher: "*")
    entries = []
    assert _event_has_expected_hook(entries, spec, "PreToolUse", 5) is False
    
    entries_after = _merge_event_groups(entries, spec, "PreToolUse", 5)
    assert len(entries_after) == 1
    assert _event_has_expected_hook(entries_after, spec, "PreToolUse", 5) is True
    
    # 2. 扁平事件 PreInvocation
    entries_flat = []
    assert _event_has_expected_hook(entries_flat, spec, "PreInvocation", 5) is False
    
    entries_flat_after = _merge_event_groups(entries_flat, spec, "PreInvocation", 5)
    assert len(entries_flat_after) == 1
    assert isinstance(entries_flat_after[0], dict)
    assert entries_flat_after[0].get("type") == "command"
    assert _event_has_expected_hook(entries_flat_after, spec, "PreInvocation", 5) is True


