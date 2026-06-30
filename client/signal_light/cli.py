"""Command line interface for AI agent signal lights (ESP8266 version)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Sequence

from signal_light.agent_signals import SIGNALS
from signal_light import esp
from signal_light.session_manager import SessionManager

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.cli")


def _load_dotenv() -> None:
    """Load client/.env if present.  Existing env vars take precedence."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    logger.debug("加载 .env 配置文件: %s", env_path)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal-light",
        description="Control an ESP8266-connected traffic signal light.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="list available lamp-language signals")
    subparsers.add_parser("status", help="show aggregated session state from ESP")

    play = subparsers.add_parser("play", help="send one signal to the ESP8266")
    play.add_argument(
        "signal",
        choices=sorted(set(SIGNALS) | {"turn_end"}),
        help="signal name",
    )
    play.add_argument("--session-id", default="global", help="session identifier")
    play.add_argument("--quiet", action="store_true")

    subparsers.add_parser("reset", help="clear all sessions and turn off lights")
    subparsers.add_parser("test", help="quick red/yellow/green test sequence")
    subparsers.add_parser("bark-test", help="send a test Bark push notification")

    # Hook subcommands
    hook = subparsers.add_parser("codex-hook", help="Codex hook adapter")
    hook.add_argument("event", nargs="?")
    hook.add_argument("--event", dest="event_option")

    cc_hook = subparsers.add_parser("claude-code-hook", help="Claude Code hook adapter")
    cc_hook.add_argument("event", nargs="?")
    cc_hook.add_argument("--event", dest="event_option")

    antigravity_hook = subparsers.add_parser("antigravity-hook", help="Antigravity hook adapter")
    antigravity_hook.add_argument("event", nargs="?")
    antigravity_hook.add_argument("--event", dest="event_option")

    install_hooks = subparsers.add_parser("install-hooks", help="install or repair local agent hooks")
    install_hooks.add_argument(
        "--agent", action="append", dest="agents",
        help="agent to install: codex, claude-code, or antigravity",
    )
    install_hooks.add_argument("--all", action="store_true", help="install all supported agents")
    install_hooks.add_argument("-y", "--yes", action="store_true", help="accept default selection")
    install_hooks.add_argument("--dry-run", action="store_true", help="show changes without writing")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logger.info("CLI 启动，命令行输入参数: %s", argv if argv is not None else sys.argv[1:])
    _load_dotenv()
    logger.debug("当前环境变量: SIGNAL_LIGHT_HOST=%s, BARK_SERVER_URL=%s", 
                 os.environ.get("SIGNAL_LIGHT_HOST"), 
                 os.environ.get("BARK_SERVER_URL"))
                 
    args = build_parser().parse_args(argv)
    logger.info("解析命令成功: command=%s", args.command)

    if args.command == "list":
        return list_signals()
    if args.command == "play":
        return play_signal(args.signal, session_id=args.session_id, quiet=args.quiet)
    if args.command == "status":
        return show_status()
    if args.command == "reset":
        return do_reset()
    if args.command == "test":
        return run_test()
    if args.command == "bark-test":
        return bark_test()
    if args.command == "codex-hook":
        from signal_light.codex_hook import read_codex_hook_input, choose_signal, session_key

        logger.info("进入 Codex Hook 适配器分支")
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
        event = args.event_option or args.event
        hook_argv = ["signal-light", "--event", event] if event else ["signal-light"]
        
        logger.debug("Codex Hook stdin 输入内容: %s", stdin_text)
        hook_input = read_codex_hook_input(hook_argv, stdin_text, os.environ)
        logger.info("Codex Hook 解析结果: event_name=%s, payload=%s", hook_input.event_name, hook_input.payload)
        
        signal = choose_signal(hook_input)
        key = session_key(hook_input, os.environ)
        logger.info("Codex Hook 决策结果: 选择信号=%s, Session Key=%s", signal, key)
        if signal is None:
            return 0
        return play_hook_signal(signal, session_key=key)
    if args.command == "claude-code-hook":
        from signal_light.claude_code_hook import read_hook_input, choose_signal, session_key

        logger.info("进入 Claude Code Hook 适配器分支")
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
        event = args.event_option or args.event
        hook_argv = ["signal-light", "--event", event] if event else ["signal-light"]
        
        logger.debug("Claude Code Hook stdin 输入内容: %s", stdin_text)
        hook_input = read_hook_input(hook_argv, stdin_text)
        logger.info("Claude Code Hook 解析结果: event_name=%s, payload=%s", hook_input.event_name, hook_input.payload)
        
        signal = choose_signal(hook_input)
        key = session_key(hook_input, os.environ)
        logger.info("Claude Code Hook 决策结果: 选择信号=%s, Session Key=%s", signal, key)
        if signal is None:
            return 0
        return play_hook_signal(signal, session_key=key)
    if args.command == "antigravity-hook":
        from signal_light.antigravity_hook import read_hook_input, choose_signal, session_key, process_and_get_output

        logger.info("进入 Antigravity Hook 适配器分支")
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
        event = args.event_option or args.event
        hook_argv = ["signal-light", "--event", event] if event else ["signal-light"]
        
        logger.debug("Antigravity Hook stdin 输入内容: %s", stdin_text)
        hook_input = read_hook_input(hook_argv, stdin_text)
        logger.info("Antigravity Hook 解析结果: event_name=%s, payload=%s", hook_input.event_name, hook_input.payload)
        
        signal = choose_signal(hook_input)
        key = session_key(hook_input, os.environ)
        logger.info("Antigravity Hook 决策结果: 选择信号=%s, Session Key=%s", signal, key)

        # 尝试播放信号，即使失败也不抛出导致 AI 挂掉的异常
        if signal is not None:
            try:
                play_hook_signal(signal, session_key=key)
            except Exception as exc:
                logger.warning("警告: 播放信号灯失败: %s", exc, exc_info=True)
                print(f"警告: 播放信号灯失败: {exc}", file=sys.stderr)

        # 始终输出符合 Antigravity 契约的输出
        output_data = process_and_get_output(hook_input)
        logger.info("返回 Antigravity 输出 JSON: %s", output_data)
        print(json.dumps(output_data))
        return 0
    if args.command == "install-hooks":
        from signal_light.hook_installer import run_install_wizard

        logger.info("进入 Install Hooks 分支，准备执行安装向导")
        try:
            return run_install_wizard(
                selected_agents=args.agents,
                all_agents=args.all,
                yes=args.yes,
                dry_run=args.dry_run,
            )
        except ValueError as exc:
            logger.error("安装向导运行异常: %s", exc, exc_info=True)
            print(str(exc), file=sys.stderr)
            return 2

    build_parser().print_help()
    return 2


def list_signals() -> int:
    logger.info("开始列出信号语...")
    for signal in SIGNALS.values():
        print(f"- {signal.name}: {signal.summary} {signal.attention}")
    return 0


def play_signal(signal_name: str, *, session_id: str = "global", quiet: bool = False) -> int:
    logger.info("play_signal: signal_name=%s, session_id=%s, quiet=%s", signal_name, session_id, quiet)
    try:
        mgr = SessionManager()
        result = mgr.handle_signal(session_id, signal_name)
        conn = esp.get_connection()
        if result.notice_first:
            esp.send_pattern(conn, "notice_green")
            time.sleep(2.0)
        esp.send_pattern(conn, result.pattern, timeout=300)
        if not quiet:
            print(f"Signal: {signal_name} | Pattern: {result.pattern}")
        logger.info("信号播放成功，pattern=%s, notice_first=%s", result.pattern, result.notice_first)
        return 0
    except esp.ESPConnectionError as exc:
        logger.error("play_signal 失败: %s", exc, exc_info=True)
        print(str(exc), file=sys.stderr)
        return 1


def play_hook_signal(signal_name: str, *, session_key: str = "global") -> int:
    logger.info("play_hook_signal: signal_name=%s, session_key=%s", signal_name, session_key)
    try:
        mgr = SessionManager()
        result = mgr.handle_signal(session_key, signal_name)
        conn = esp.get_connection()
        if result.notice_first:
            esp.send_pattern(conn, "notice_green")
            time.sleep(2.0)
        esp.send_pattern(conn, result.pattern, timeout=300)

        # Bark 推送
        bark_url = os.environ.get("BARK_SERVER_URL", "").strip()
        from signal_light import bark
        if bark_url and bark.should_notify(signal_name):
            logger.info("触发 Bark 推送通知...")
            bark.notify(bark_url, signal_name, session_id=session_key)

        return 0
    except esp.ESPConnectionError as exc:
        logger.error("play_hook_signal 失败: %s", exc, exc_info=True)
        print(str(exc), file=sys.stderr)
        return 1


def show_status() -> int:
    logger.info("获取并显示信号灯状态...")
    mgr = SessionManager()
    status = mgr.get_status()
    # Also try ESP status
    try:
        conn = esp.get_connection()
        esp_status = esp.get_status(conn)
        status["esp"] = esp_status
    except esp.ESPConnectionError:
        status["esp"] = {"error": "unreachable"}
    print(json.dumps(status, ensure_ascii=False, indent=2))
    logger.info("成功获取状态: %s", status)
    return 0


def do_reset() -> int:
    logger.info("重置信号灯状态...")
    mgr = SessionManager()
    cleared = mgr.reset()
    try:
        conn = esp.get_connection()
        esp.reset(conn)
    except esp.ESPConnectionError as exc:
        logger.warning("ESP reset failed (sessions already cleared): %s", exc)
    print(f"Reset: {cleared} sessions cleared")
    logger.info("重置成功: %s sessions cleared", cleared)
    return 0


def run_test() -> int:
    """Cycle through all LED patterns for hardware testing."""
    logger.info("运行测试序列...")
    patterns = ["green_on", "work_cycle", "flash_yellow", "flash_red", "notice_green", "off"]
    try:
        conn = esp.get_connection()
        for pattern in patterns:
            logger.info("测试序列: 发送 pattern %s", pattern)
            esp.send_pattern(conn, pattern)
            time.sleep(2)
        print("Test complete.")
        logger.info("测试序列执行完成")
        return 0
    except esp.ESPConnectionError as exc:
        logger.error("run_test 失败: %s", exc, exc_info=True)
        print(str(exc), file=sys.stderr)
        return 1


def bark_test() -> int:
    """Send a test Bark push notification."""
    logger.info("运行 Bark 推送测试...")
    from signal_light import bark

    server_url = os.environ.get("BARK_SERVER_URL", "").strip()
    if not server_url:
        err_msg = (
            "BARK_SERVER_URL is not set.\n"
            "Example: export BARK_SERVER_URL=https://api.day.app/YOURKEY"
        )
        logger.warning("bark_test 失败: BARK_SERVER_URL 未配置")
        print(err_msg, file=sys.stderr)
        return 1

    logger.info("发送 Bark 测试推送，目标 URL: %s", server_url)
    bark.notify(server_url, "attention", session_id="bark-test")
    print("Bark test notification sent.")
    logger.info("Bark 推送测试执行完毕")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
