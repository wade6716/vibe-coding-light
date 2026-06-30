"""Bark push notification integration for the signal light."""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from typing import Mapping

# 初始化模块级别的 Logger
logger = logging.getLogger("signal_light.bark")

# Signals that require human attention — default set for Bark notifications.
_DEFAULT_NOTIFY_SIGNALS = frozenset({"blocked", "permission", "attention"})


def _notify_signals() -> set[str]:
    """Return the set of signals that should trigger a Bark notification."""
    raw = os.environ.get("BARK_NOTIFY_SIGNALS", "").strip()
    if not raw:
        return set(_DEFAULT_NOTIFY_SIGNALS)
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


def should_notify(signal: str) -> bool:
    """Check whether *signal* is in the current notify set."""
    return signal.lower() in _notify_signals()


def notify(server_url: str, signal: str, session_id: str = "") -> None:
    """Send a Bark push notification.  Errors are printed to stderr, never raised."""
    from signal_light.agent_signals import SIGNALS

    info = SIGNALS.get(signal)
    title = f"Signal: {signal}"
    body = info.attention if info else signal

    if session_id:
        body = f"{body}\n({session_id})"

    payload_dict = {
        "title": title,
        "body": body,
        "group": "signal-light",
    }
    payload = json.dumps(payload_dict).encode()

    url = server_url.rstrip("/") + "/"
    logger.info("发送 Bark 推送通知: signal=%s, url=%s, payload=%s", signal, url, payload_dict)
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp_data = resp.read()
            logger.debug("Bark 服务器响应成功: %s", resp_data)
    except Exception as exc:
        err_msg = f"[bark] notification failed: {exc}"
        logger.error(err_msg, exc_info=True)
        print(err_msg, file=sys.stderr)

