"""Codex hook adapter for the signal light lamp language."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping

from signal_light.agent_signals import SIGNALS

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.codex_hook")

EVENT_TO_SIGNAL = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "thinking",
    "PreToolUse": "working",
    "PostToolUse": "tool_done",
    "PermissionRequest": "permission",
    "Stop": "turn_end",
    "SessionEnd": "session_end",
}

FAILURE_SIGNALS = {
    "error": "blocked",
    "failed": "blocked",
    "failure": "blocked",
    "exception": "blocked",
}


@dataclass(frozen=True)
class CodexHookInput:
    event_name: str
    payload: Mapping[str, Any]


def read_codex_hook_input(argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> CodexHookInput:
    logger.debug("Codex Hook 原始命令行参数: %s", argv)
    event_name = _event_from_args(argv)
    payload: Mapping[str, Any] = {}

    if stdin_text.strip():
        try:
            parsed = json.loads(stdin_text)
            if isinstance(parsed, Mapping):
                payload = parsed
                event_name = event_name or _event_from_payload(parsed)
        except json.JSONDecodeError as exc:
            logger.warning("解析 stdin JSON 失败: %s", exc)
            payload = {"raw": stdin_text}

    event_name = event_name or environ.get("CODEX_HOOK_EVENT") or environ.get("HOOK_EVENT") or "Stop"
    hook_input = CodexHookInput(event_name=event_name, payload=payload)
    logger.info("Codex Hook 输入解析完毕: event_name=%s, payload_keys=%s", 
                hook_input.event_name, list(hook_input.payload.keys()))
    return hook_input


def choose_signal(hook_input: CodexHookInput) -> str:
    explicit = _first_string(
        hook_input.payload,
        ("signal", "signal_name", "lamp_signal"),
    )
    if explicit:
        normalized = explicit.strip().lower()
        if normalized in SIGNALS:
            logger.info("显式指定信号: %s", normalized)
            return normalized

    status = _first_string(hook_input.payload, ("status", "state"))
    if status:
        normalized_status = status.strip().lower()
        if normalized_status in SIGNALS:
            logger.info("通过 payload 状态决定播放: %s", normalized_status)
            return normalized_status
        if normalized_status in FAILURE_SIGNALS:
            sig = FAILURE_SIGNALS[normalized_status]
            logger.info("通过 payload 错误状态决定播放: %s", sig)
            return sig

    failure_marker = _structured_failure_marker(hook_input.payload)
    if failure_marker:
        sig = FAILURE_SIGNALS[failure_marker]
        logger.info("通过 structured 错误标记决定播放: %s", sig)
        return sig

    sig = EVENT_TO_SIGNAL.get(hook_input.event_name, EVENT_TO_SIGNAL.get(hook_input.event_name.strip(), "attention"))
    logger.info("依据事件名 %s 映射决定播放信号: %s", hook_input.event_name, sig)
    return sig


def session_key(hook_input: CodexHookInput, environ: Mapping[str, str]) -> str:
    explicit = _first_string(
        hook_input.payload,
        (
            "session_id",
            "conversation_id",
            "thread_id",
            "chat_id",
            "codex_session_id",
        ),
    )
    if explicit:
        logger.debug("从 payload 显式键值提取会话 ID: %s", explicit)
        return explicit.strip()

    nested = _find_nested_string(
        hook_input.payload,
        (
            "session_id",
            "conversation_id",
            "thread_id",
            "codex_session_id",
        ),
    )
    if nested:
        logger.debug("从 payload 嵌套键值提取会话 ID: %s", nested)
        return nested

    for key in (
        "CODEX_SESSION_ID",
        "CODEX_CONVERSATION_ID",
        "CODEX_THREAD_ID",
    ):
        value = environ.get(key)
        if value:
            logger.debug("从环境变量 %s 提取会话 ID: %s", key, value)
            return value.strip()

    cwd = _first_string(hook_input.payload, ("cwd", "workspace", "workspace_dir", "project_dir"))
    if cwd:
        skey = f"cwd:{cwd.strip()}"
        logger.debug("使用工作目录作为备用会话 ID: %s", skey)
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


def _event_from_payload(payload: Mapping[str, Any]) -> str | None:
    return _first_string(
        payload,
        ("hook_event_name", "event_name", "event", "hook", "type"),
    )


def _first_string(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _find_nested_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        direct = _first_string(value, keys)
        if direct:
            return direct.strip()
        for child in value.values():
            found = _find_nested_string(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_nested_string(child, keys)
            if found:
                return found
    return None


def _structured_failure_marker(payload: Mapping[str, Any]) -> str | None:
    return _find_failure_marker(
        payload,
        (
            "error",
            "failure",
            "exception",
            "error_type",
            "error_message",
            "failure_reason",
            "exit_status",
            "tool_error",
        ),
    )


def _find_failure_marker(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in FAILURE_SIGNALS or normalized_key in keys:
                marker = _failure_marker_from_value(child)
                if marker:
                    return marker
            found = _find_failure_marker(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_failure_marker(child, keys)
            if found:
                return found
    return None


def _failure_marker_from_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "error" if value else None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return "failed" if value != 0 else None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized or normalized in {"0", "false", "no", "none", "null", "success", "ok"}:
            return None
        for marker in FAILURE_SIGNALS:
            if marker in normalized:
                return marker
        return "error"
    return "error"


def main() -> int:
    logger.info("Codex Hook 脚本单独启动")
    from signal_light import esp
    from signal_light import bark

    stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    logger.debug("读取到的 stdin 内容: %s", stdin_text)
    hook_input = read_codex_hook_input(sys.argv, stdin_text, os.environ)
    signal = choose_signal(hook_input)
    key = session_key(hook_input, os.environ)
    logger.info("Codex Hook 决策: 选择信号=%s, Session Key=%s", signal, key)

    try:
        conn = esp.get_connection()
        esp.send_signal(conn, signal, session_id=key)
    except esp.ESPConnectionError as exc:
        logger.error("发送信号失败: %s", exc, exc_info=True)
        print(str(exc), file=sys.stderr)
        return 1

    bark_url = os.environ.get("BARK_SERVER_URL", "").strip()
    if bark_url and bark.should_notify(signal):
        logger.info("触发 Bark 推送通知...")
        bark.notify(bark_url, signal, session_id=key)

    logger.info("Codex Hook 脚本执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

