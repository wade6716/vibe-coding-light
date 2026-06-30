"""Claude Code hook adapter for the signal light lamp language."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping

from signal_light.agent_signals import SIGNALS

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.claude_code_hook")

EVENT_TO_SIGNAL = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "thinking",
    "PreToolUse": "working",
    "PostToolUse": "tool_done",
    "PostToolUseFailure": "blocked",
    "PreCompact": "working",
    "SubagentStart": "working",
    "SubagentStop": "tool_done",
    "Stop": "turn_end",
    "Notification": "attention",
    "PermissionRequest": "permission",
    "SessionEnd": "session_end",
}

STOP_REASON_SIGNAL = {
    "max_tokens": "blocked",
    "error": "blocked",
}


@dataclass(frozen=True)
class ClaudeCodeHookInput:
    event_name: str
    payload: Mapping[str, Any]


def read_hook_input(argv: list[str], stdin_text: str) -> ClaudeCodeHookInput:
    logger.debug("Claude Code Hook 原始命令行参数: %s", argv)
    event_name = _event_from_args(argv)
    payload: Mapping[str, Any] = {}

    if stdin_text.strip():
        try:
            parsed = json.loads(stdin_text)
            if isinstance(parsed, Mapping):
                payload = parsed
                event_name = event_name or parsed.get("event") or parsed.get("hook_event_name")
        except json.JSONDecodeError as exc:
            logger.warning("解析 stdin JSON 失败: %s", exc)
            payload = {"raw": stdin_text}

    event_name = event_name or "Stop"
    hook_input = ClaudeCodeHookInput(event_name=event_name, payload=payload)
    logger.info("Claude Code Hook 输入解析完毕: event_name=%s, payload_keys=%s", 
                hook_input.event_name, list(hook_input.payload.keys()))
    return hook_input


def choose_signal(hook_input: ClaudeCodeHookInput) -> str:
    explicit = hook_input.payload.get("signal") or hook_input.payload.get("signal_name")
    if isinstance(explicit, str) and explicit.strip().lower() in SIGNALS:
        sig = explicit.strip().lower()
        logger.info("显式指定信号: %s", sig)
        return sig

    if hook_input.event_name == "Stop":
        stop_reason = hook_input.payload.get("stop_reason")
        if isinstance(stop_reason, str) and stop_reason in STOP_REASON_SIGNAL:
            sig = STOP_REASON_SIGNAL[stop_reason]
            logger.info("事件为 Stop，基于 stop_reason=%s 决定播放: %s", stop_reason, sig)
            return sig

    sig = EVENT_TO_SIGNAL.get(hook_input.event_name)
    if sig is None:
        logger.info("事件 %s 未映射，忽略", hook_input.event_name)
        return None
    logger.info("依据事件名 %s 映射决定播放信号: %s", hook_input.event_name, sig)
    return sig


def session_key(hook_input: ClaudeCodeHookInput, environ: Mapping[str, str]) -> str:
    sid = hook_input.payload.get("session_id")
    if isinstance(sid, str) and sid.strip():
        logger.debug("从 payload.session_id 提取会话 ID: %s", sid)
        return sid.strip()

    for key in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = environ.get(key)
        if value:
            logger.debug("从环境变量 %s 提取会话 ID: %s", key, value)
            return value.strip()

    cwd = hook_input.payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        skey = f"cwd:{cwd.strip()}"
        logger.debug("使用当前工作目录作为备用会话 ID: %s", skey)
        return skey

    logger.debug("未提取到特定会话 ID，默认使用: global")
    return "global"


def _event_from_args(argv: list[str]) -> str | None:
    for index, value in enumerate(argv):
        if value in {"--event", "-e"} and index + 1 < len(argv):
            return argv[index + 1]
        if value.startswith("--event="):
            return value.split("=", 1)[1]
    if len(argv) >= 2 and not argv[1].startswith("-"):
        return argv[1]
    return None


def main() -> int:
    logger.info("Claude Code Hook 脚本单独启动")
    from signal_light import esp
    from signal_light import bark

    stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    logger.debug("读取到的 stdin 内容: %s", stdin_text)
    hook_input = read_hook_input(sys.argv, stdin_text)
    signal = choose_signal(hook_input)
    key = session_key(hook_input, os.environ)
    logger.info("Claude Code Hook 决策: 选择信号=%s, Session Key=%s", signal, key)

    if signal is None:
        return 0

    from signal_light.session_manager import SessionManager
    mgr = SessionManager()
    result = mgr.handle_signal(key, signal)

    try:
        conn = esp.get_connection()
        if result.notice_first:
            esp.send_pattern(conn, "notice_green")
            import time; time.sleep(2.0)
        esp.send_pattern(conn, result.pattern, timeout=300)
    except esp.ESPConnectionError as exc:
        logger.error("发送信号失败: %s", exc, exc_info=True)
        print(str(exc), file=sys.stderr)
        return 1

    bark_url = os.environ.get("BARK_SERVER_URL", "").strip()
    if bark_url and bark.should_notify(signal):
        logger.info("触发 Bark 推送通知...")
        bark.notify(bark_url, signal, session_id=key)

    logger.info("Claude Code Hook 脚本执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

