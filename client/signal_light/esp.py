"""HTTP client for the ESP8266 signal light."""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.esp")

# Bypass proxy for .local (mDNS) and private IP addresses – the ESP is on
# the local network and should never be reached through an HTTP proxy.
_no_proxy_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
)


@dataclass
class ESPConnection:
    """Configuration for connecting to the ESP8266."""

    host: str
    port: int = 80
    timeout: float = 5.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


class ESPConnectionError(RuntimeError):
    """Raised when the ESP8266 is unreachable."""


def discover_host() -> str | None:
    """Try mDNS discovery, then fall back to SIGNAL_LIGHT_HOST env var."""
    logger.debug("开始寻找信号灯设备...")
    # 1. Try mDNS
    try:
        addr = socket.getaddrinfo("signal-light.local", 80)
        if addr:
            logger.info("通过 mDNS 成功发现设备: signal-light.local")
            return "signal-light.local"
    except (socket.gaierror, OSError) as exc:
        logger.debug("通过 mDNS 发现设备失败: %s", exc)

    # 2. Try env var
    host = os.environ.get("SIGNAL_LIGHT_HOST", "").strip()
    if host:
        logger.info("使用环境变量 SIGNAL_LIGHT_HOST 指定的设备地址: %s", host)
        return host

    logger.warning("未能发现信号灯设备。请确保 signal-light.local 可达，或者设置了 SIGNAL_LIGHT_HOST 环境变量。")
    return None


def get_connection() -> ESPConnection:
    """Get a connection, raising if no host can be found."""
    host = discover_host()
    if not host:
        raise ESPConnectionError(
            "Cannot find signal light. Set SIGNAL_LIGHT_HOST=<ip> or ensure "
            "signal-light.local is reachable via mDNS."
        )
    conn = ESPConnection(host=host)
    logger.debug("创建连接配置: %s", conn)
    return conn


def send_signal(conn: ESPConnection, signal: str, session_id: str = "global") -> dict[str, Any]:
    """POST /signal to the ESP8266."""
    payload_dict = {"signal": signal, "session_id": session_id}
    payload = json.dumps(payload_dict).encode()
    url = f"{conn.base_url}/signal"
    logger.info("向 ESP8266 发送信号: signal=%s, session_id=%s, url=%s", signal, session_id, url)
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with _no_proxy_opener.open(req, timeout=conn.timeout) as resp:
            resp_data = resp.read()
            logger.debug("ESP8266 原始响应: %s", resp_data)
            result = json.loads(resp_data)
            logger.info("ESP8266 响应成功: %s", result)
            return result
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        err_msg = f"Failed to send signal to {conn.host}: {exc}"
        logger.error(err_msg, exc_info=True)
        raise ESPConnectionError(err_msg) from exc


def get_status(conn: ESPConnection) -> dict[str, Any]:
    """GET /status from the ESP8266."""
    url = f"{conn.base_url}/status"
    logger.debug("获取 ESP8266 状态: %s", url)
    try:
        with _no_proxy_opener.open(url, timeout=conn.timeout) as resp:
            resp_data = resp.read()
            result = json.loads(resp_data)
            logger.debug("获取状态成功: %s", result)
            return result
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        err_msg = f"Failed to get status from {conn.host}: {exc}"
        logger.error(err_msg, exc_info=True)
        raise ESPConnectionError(err_msg) from exc


def reset(conn: ESPConnection) -> dict[str, Any]:
    """POST /reset to the ESP8266."""
    url = f"{conn.base_url}/reset"
    logger.info("重置 ESP8266 信号灯状态: %s", url)
    req = urllib.request.Request(url, method="POST")
    try:
        with _no_proxy_opener.open(req, timeout=conn.timeout) as resp:
            resp_data = resp.read()
            result = json.loads(resp_data)
            logger.info("重置成功: %s", result)
            return result
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        err_msg = f"Failed to reset {conn.host}: {exc}"
        logger.error(err_msg, exc_info=True)
        raise ESPConnectionError(err_msg) from exc

