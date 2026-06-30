"""单元测试：验证日志初始化、日志级别设置及自定义日志文件的写入逻辑。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from signal_light.logger import setup_logging


def test_setup_logging_default(monkeypatch, tmp_path) -> None:
    """测试默认日志初始化，默认应写入系统临时文件夹。"""
    # 强制清理已有的 logger handlers 以便重复测试
    logger = logging.getLogger("signal_light")
    logger.handlers.clear()

    # 模拟临时文件夹，确保有写入权限
    temp_log = tmp_path / "signal-light.log"
    monkeypatch.setenv("SIGNAL_LIGHT_LOG_FILE", str(temp_log))
    monkeypatch.setenv("SIGNAL_LIGHT_LOG_LEVEL", "DEBUG")

    setup_logging()

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.FileHandler)

    # 尝试写入一条测试日志
    logger.info("测试日志写入")
    logger.handlers[0].flush()
    logger.handlers[0].close()

    assert temp_log.exists()
    content = temp_log.read_text(encoding="utf-8")
    assert "测试日志写入" in content
    assert "[INFO]" in content
    assert "test_logger.py" in content


def test_setup_logging_invalid_path(monkeypatch, capsys) -> None:
    """测试日志文件路径无效或无写入权限时，是否能优雅回退。"""
    logger = logging.getLogger("signal_light")
    logger.handlers.clear()

    # 故意设置一个绝对无法创建的路径（例如目录也是个文件）
    invalid_path = "/this_directory_does_not_exist_and_cannot_write/signal-light.log"
    monkeypatch.setenv("SIGNAL_LIGHT_LOG_FILE", invalid_path)

    # setup_logging 应该捕捉异常不崩溃，并且配置 NullHandler 
    setup_logging()

    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)
