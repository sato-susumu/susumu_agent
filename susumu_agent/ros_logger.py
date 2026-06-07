"""loguru を ROS2 ロガーにブリッジするユーティリティ。"""
from loguru import logger

try:
    import rclpy.logging as _rclpy_logging
    _ROS2_LOGGING_AVAILABLE = True
except ImportError:
    _rclpy_logging = None
    _ROS2_LOGGING_AVAILABLE = False


class RosLogger:
    _LEVEL_MAP: dict[str, str] = {
        "DEBUG":    "debug",
        "INFO":     "info",
        "SUCCESS":  "info",
        "WARNING":  "warning",
        "ERROR":    "error",
        "CRITICAL": "fatal",
    }

    @classmethod
    def sink(cls, message) -> None:
        if not _ROS2_LOGGING_AVAILABLE:
            return
        record = message.record
        name = record["extra"].get("name") or record["name"]
        level = cls._LEVEL_MAP.get(record["level"].name, "info")
        ros_logger = _rclpy_logging.get_logger(name)
        getattr(ros_logger, level)(record["message"])

    @staticmethod
    def setup(log_path: str | None = None) -> None:
        """loguru の sink を設定する。log_path を指定するとファイルにも出力する。"""
        logger.remove()
        logger.add(RosLogger.sink, format="{message}")
        if log_path:
            logger.add(
                log_path,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} [{level}] [{name}]: {message}",
                encoding="utf-8",
            )

    @staticmethod
    def get(name: str):
        """name を bind した loguru ロガーを返す。"""
        return logger.bind(name=name)


# 後方互換エイリアス
def setup_loguru(log_path: str | None = None) -> None:
    RosLogger.setup(log_path)


def get_logger(name: str):
    return RosLogger.get(name)
