"""loguru を ROS2 ロガーにブリッジするユーティリティ。"""
import rclpy.logging
from loguru import logger

_ROS2_LEVEL_MAP = {
    "DEBUG":    "debug",
    "INFO":     "info",
    "SUCCESS":  "info",
    "WARNING":  "warning",
    "ERROR":    "error",
    "CRITICAL": "fatal",
}


def _ros2_sink(message):
    record = message.record
    # extra["name"] が bind されていればそれを使い、なければモジュール名を使う
    name = record["extra"].get("name") or record["name"]
    level = _ROS2_LEVEL_MAP.get(record["level"].name, "info")
    ros_logger = rclpy.logging.get_logger(name)
    getattr(ros_logger, level)(record["message"])


def setup_loguru(log_path: str | None = None) -> None:
    """loguru の sink を設定する。log_path を指定するとファイルにも出力する。"""
    logger.remove()
    logger.add(_ros2_sink, format="{message}")
    if log_path:
        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} [{level}] [{name}]: {message}",
            encoding="utf-8",
        )


def get_logger(name: str):
    """name を bind した loguru ロガーを返す。"""
    return logger.bind(name=name)
