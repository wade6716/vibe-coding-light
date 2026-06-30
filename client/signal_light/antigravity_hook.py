"""Antigravity 运行周期 Hook 适配器。"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping

from signal_light.agent_signals import SIGNALS

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.antigravity_hook")


@dataclass(frozen=True)
class AntigravityHookInput:
    event_name: str
    payload: Mapping[str, Any]


def read_hook_input(argv: list[str], stdin_text: str) -> AntigravityHookInput:
    """读取并解析 Antigravity 传入的 Hook 事件与数据。"""
    logger.debug("Antigravity 原始命令行参数: %s", argv)
    # 优先从命令行参数中提取事件名称（例如 PreToolUse, PostToolUse 等）
    event_name = _event_from_args(argv)
    payload: Mapping[str, Any] = {}

    if stdin_text.strip():
        try:
            parsed = json.loads(stdin_text)
            if isinstance(parsed, Mapping):
                payload = parsed
                # 兼容可能在 JSON 中已包含的事件名称
                event_name = event_name or parsed.get("event") or parsed.get("hook_event_name")
        except json.JSONDecodeError as exc:
            logger.warning("解析 stdin JSON 失败: %s", exc)
            payload = {"raw": stdin_text}

    # 备用方案：根据 JSON 中的特征字段推断事件名称
    if not event_name:
        if "toolCall" in payload:
            event_name = "PreToolUse"
        elif "error" in payload and "stepIdx" in payload:
            event_name = "PostToolUse"
        elif "executionNum" in payload:
            event_name = "Stop"
        elif "invocationNum" in payload:
            # PreInvocation 与 PostInvocation 结构一致，默认推断为 PreInvocation
            event_name = "PreInvocation"
        else:
            event_name = "Stop"
        logger.debug("通过特征字段推断事件名称: %s", event_name)

    hook_input = AntigravityHookInput(event_name=event_name, payload=payload)
    logger.info("Antigravity Hook 输入解析完毕: event_name=%s, payload_keys=%s", 
                hook_input.event_name, list(hook_input.payload.keys()))
    return hook_input


def choose_signal(hook_input: AntigravityHookInput) -> str:
    """根据 Hook 事件与数据选择对应的灯光信号。"""
    # 允许在 payload 中显式指定信号
    explicit = hook_input.payload.get("signal") or hook_input.payload.get("signal_name")
    if isinstance(explicit, str) and explicit.strip().lower() in SIGNALS:
        sig = explicit.strip().lower()
        logger.info("显式指定信号: %s", sig)
        return sig

    event = hook_input.event_name

    if event == "PreToolUse":
        tool_call = hook_input.payload.get("toolCall")
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name")
            if isinstance(tool_name, str):
                if tool_name == "ask_permission" or tool_name.endswith(":ask_permission"):
                    logger.info("检测到权限请求工具: %s, 决定播放: permission", tool_name)
                    return "permission"
                elif tool_name == "ask_question" or tool_name.endswith(":ask_question"):
                    logger.info("检测到提问工具: %s, 决定播放: attention", tool_name)
                    return "attention"
                elif tool_name == "run_command" or tool_name.endswith(":run_command"):
                    # run_command 通常需要用户弹窗授权确认，会产生阻塞，因此播放 permission（红灯闪烁）提醒用户介入
                    logger.info("检测到命令执行工具: %s（需要弹窗授权），决定播放: permission", tool_name)
                    return "permission"
        logger.info("事件 PreToolUse, 默认播放: working")
        return "working"

    elif event == "PostToolUse":
        # 如果出错，指示阻塞状态
        error = hook_input.payload.get("error")
        if error:
            logger.info("工具执行出错, 决定播放: blocked")
            return "blocked"
        logger.info("工具执行成功, 决定播放: tool_done")
        return "tool_done"

    elif event == "PreInvocation":
        logger.info("事件 PreInvocation, 决定播放: thinking")
        return "thinking"

    elif event == "PostInvocation":
        logger.info("事件 PostInvocation, 决定播放: tool_done")
        return "tool_done"

    elif event == "Stop":
        error = hook_input.payload.get("error")
        reason = hook_input.payload.get("terminationReason")
        fully_idle = hook_input.payload.get("fullyIdle", True)

        if error or reason == "error":
            logger.info("执行终止（存在错误）, 决定播放: blocked")
            return "blocked"
        
        # 如果会话完全空闲，代表任务完成
        if fully_idle:
            logger.info("会话完全空闲, 任务已完成, 决定播放: session_done")
            return "session_done"
        logger.info("本次 Turn 结束, 但任务未完成, 决定播放: turn_end")
        return "turn_end"

    logger.info("未知或未匹配事件 %s，忽略", event)
    return None


def session_key(hook_input: AntigravityHookInput, environ: Mapping[str, str]) -> str:
    """解析并提取会话 ID，以实现多会话共存状态管理。"""
    # 优先使用 Antigravity 传入的通用会话标识符 conversationId
    sid = hook_input.payload.get("conversationId")
    if isinstance(sid, str) and sid.strip():
        logger.debug("从 payload.conversationId 提取会话 ID: %s", sid)
        return sid.strip()

    # 尝试从环境变量读取会话标识符
    for key in ("ANTIGRAVITY_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID", "SESSION_ID"):
        value = environ.get(key)
        if value:
            logger.debug("从环境变量 %s 提取会话 ID: %s", key, value)
            return value.strip()

    # 备用方案：使用工作区路径作为会话标识符
    paths = hook_input.payload.get("workspacePaths")
    if isinstance(paths, list) and paths:
        skey = f"workspace:{paths[0]}"
        logger.debug("使用工作区路径作为备用会话 ID: %s", skey)
        return skey

    logger.debug("未提取到特定会话 ID，默认使用: global")
    return "global"


def process_and_get_output(hook_input: AntigravityHookInput) -> dict[str, Any]:
    """根据输入事件获取 Antigravity 契约所要求的输出 JSON。"""
    event = hook_input.event_name
    if event == "PreToolUse":
        return {"decision": "allow"}
    elif event == "PostToolUse":
        return {}
    elif event == "PreInvocation":
        return {"injectSteps": []}
    elif event == "PostInvocation":
        return {"injectSteps": [], "terminationBehavior": ""}
    elif event == "Stop":
        return {"decision": "allow"}
    return {}


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
    logger.info("Antigravity Hook 脚本单独启动")
    from signal_light import esp
    from signal_light import bark
    from signal_light.session_manager import SessionManager

    stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    logger.debug("读取到的 stdin 内容: %s", stdin_text)
    hook_input = read_hook_input(sys.argv, stdin_text)
    signal = choose_signal(hook_input)
    key = session_key(hook_input, os.environ)
    logger.info("Antigravity Hook 决策: 选择信号=%s, Session Key=%s", signal, key)

    output = process_and_get_output(hook_input)

    if signal is not None:
        try:
            mgr = SessionManager()
            result = mgr.handle_signal(key, signal)
            conn = esp.get_connection()
            if result.notice_first:
                esp.send_pattern(conn, "notice_green")
                import time; time.sleep(2.0)
            esp.send_pattern(conn, result.pattern, timeout=300)
        except Exception as exc:
            logger.error("发送信号失败: %s", exc, exc_info=True)
            print(str(exc), file=sys.stderr)

    bark_url = os.environ.get("BARK_SERVER_URL", "").strip()
    if signal is not None and bark_url and bark.should_notify(signal):
        logger.info("触发 Bark 推送通知...")
        bark.notify(bark_url, signal, session_id=key)

    print(json.dumps(output))
    logger.info("Antigravity Hook 脚本执行完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

