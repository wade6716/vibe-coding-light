"""Tests for the ESP8266 HTTP client module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from signal_light import esp


def test_discover_host_returns_env_var_when_mdns_fails(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.100")

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        host = esp.discover_host()

    assert host == "192.168.1.100"


def test_discover_host_returns_mdns_host_first(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.100")

    with patch("socket.getaddrinfo", return_value=[("family", "type", "proto", "canonname", ("192.168.1.50", 80))]):
        host = esp.discover_host()

    assert host == "signal-light.local"


def test_discover_host_returns_none_when_nothing_found(monkeypatch) -> None:
    monkeypatch.delenv("SIGNAL_LIGHT_HOST", raising=False)

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        host = esp.discover_host()

    assert host is None


def test_get_connection_raises_when_no_host(monkeypatch) -> None:
    monkeypatch.delenv("SIGNAL_LIGHT_HOST", raising=False)

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        with pytest.raises(esp.ESPConnectionError, match="Cannot find signal light"):
            esp.get_connection()


def test_get_connection_returns_connection_with_env_host(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "10.0.0.5")

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        conn = esp.get_connection()

    assert conn.host == "10.0.0.5"
    assert conn.base_url == "http://10.0.0.5:80"


def test_send_pattern_builds_correct_request(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["data"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        resp = MagicMock()
        resp.read.return_value = json.dumps({"ok": True, "aggregate": "working"}).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        conn = esp.get_connection()

    with patch.object(esp._no_proxy_opener, "open", side_effect=fake_urlopen):
        result = esp.send_pattern(conn, "flash_yellow", timeout=300)

    assert captured["url"] == "http://192.168.1.1:80/pattern"
    assert captured["method"] == "POST"
    body = json.loads(captured["data"])
    assert body == {"pattern": "flash_yellow", "timeout": 300}
    assert result["ok"] is True
    assert result["aggregate"] == "working"


def test_send_pattern_raises_on_connection_error(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.1")

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        conn = esp.get_connection()

    with patch.object(esp._no_proxy_opener, "open", side_effect=OSError("connection refused")):
        with pytest.raises(esp.ESPConnectionError, match="Failed to send pattern"):
            esp.send_pattern(conn, "green_on")


def test_get_status_builds_correct_request(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.1")

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        conn = esp.get_connection()

    resp = MagicMock()
    resp.read.return_value = json.dumps({"aggregate": "idle", "sessions": {}}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch.object(esp._no_proxy_opener, "open", return_value=resp) as mock_open:
        result = esp.get_status(conn)

    assert result["aggregate"] == "idle"
    call_args = mock_open.call_args
    assert "status" in call_args[0][0]


def test_reset_builds_correct_request(monkeypatch) -> None:
    monkeypatch.setenv("SIGNAL_LIGHT_HOST", "192.168.1.1")

    with patch("socket.getaddrinfo", side_effect=OSError("no mDNS")):
        conn = esp.get_connection()

    resp = MagicMock()
    resp.read.return_value = json.dumps({"ok": True, "sessions_cleared": 2}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch.object(esp._no_proxy_opener, "open", return_value=resp) as mock_open:
        result = esp.reset(conn)

    assert result["ok"] is True
    assert result["sessions_cleared"] == 2
