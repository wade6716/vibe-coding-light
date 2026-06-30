"""日志配置模块，负责初始化和配置 Python 客户端的日志输出。"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path


def setup_logging() -> logging.Logger:
    """初始化并配置日志系统。

    日志输出文件可通过环境变量 SIGNAL_LIGHT_LOG_FILE 指定，默认为系统临时目录下的 signal-light.log。
    日志级别可通过环境变量 SIGNAL_LIGHT_LOG_LEVEL 指定，默认为 INFO。
    """
    logger = logging.getLogger("signal_light")
    
    # 避免重复添加 Handler
    if logger.handlers:
        return logger

    # 获取日志级别，默认为 INFO
    level_name = os.environ.get("SIGNAL_LIGHT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    # 统一的日志格式：时间 [级别] 模块名 (文件名:行号): 日志内容
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
    )

    # 获取日志保存路径，默认写入系统临时目录下的 signal-light.log
    log_file = os.environ.get("SIGNAL_LIGHT_LOG_FILE")
    if not log_file:
        log_file = os.path.join(tempfile.gettempdir(), "signal-light.log")

    try:
        log_path = Path(log_file)
        # 确保日志文件所在的目录存在
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建文件处理器，指定编码为 utf-8
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        # 如果写入文件失败（例如权限不足），优雅回退，使用 NullHandler 避免抛出异常
        logger.addHandler(logging.NullHandler())
        # 在 sys.stderr 中打印一条简短的警告
        import sys
        print(f"警告: 无法初始化日志文件 {log_file}: {exc}", file=sys.stderr)

    return logger
