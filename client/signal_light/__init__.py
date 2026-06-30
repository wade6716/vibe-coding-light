"""Traffic signal language for AI agent status lights (ESP8266 version)."""
from signal_light.agent_signals import SIGNALS, AgentSignal
from signal_light.logger import setup_logging
from signal_light.session_manager import SessionManager, SignalResult

# 自动初始化日志系统
setup_logging()

__all__ = ["SIGNALS", "AgentSignal", "setup_logging", "SessionManager", "SignalResult"]
