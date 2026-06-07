from __future__ import annotations

import math
from typing import Literal, TypedDict

SpeedLevel = Literal["low", "medium", "high"]
Direction = Literal["forward", "backward", "stop"]


class SpeedEntry(TypedDict):
    linear: float
    angular: float


SpeedMap = dict[SpeedLevel, SpeedEntry]
SpeedKeywordMap = dict[SpeedLevel, list[str]]


class RobotCapabilities:
    SPEED_MAP: SpeedMap = {
        "low":    SpeedEntry(linear=0.1, angular=0.3),
        "medium": SpeedEntry(linear=0.3, angular=0.8),
        "high":   SpeedEntry(linear=0.5, angular=1.5),
    }

    ANGULAR_VEL_DEFAULT: float = 0.8  # rad/s（rotate_robot の duration 計算用）

    MAX_DURATION_SEC: float = 30.0
    MAX_ANGLE_DEG: float = 360.0
    MIN_DURATION_SEC: float = 0.1

    EMERGENCY_KEYWORDS: frozenset[str] = frozenset({
        "ストップ", "止まれ", "とまれ", "止まって", "とまって",
        "やめて", "やめろ", "緊急停止", "stop", "STOP",
    })

    SPEED_KEYWORDS: SpeedKeywordMap = {
        "low":  ["ゆっくり", "ゆったり", "ちょっとずつ", "ちょい", "そろそろ",
                 "のんびり", "少し", "slowly", "gently", "carefully"],
        "high": ["素早く", "速く", "ダッシュ", "全力", "急いで", "全速力",
                 "fast", "quickly", "rush"],
    }

    @classmethod
    def clamp_duration(cls, value: float) -> float:
        return max(cls.MIN_DURATION_SEC, min(value, cls.MAX_DURATION_SEC))

    @classmethod
    def clamp_angle(cls, value: float) -> float:
        return max(-cls.MAX_ANGLE_DEG, min(value, cls.MAX_ANGLE_DEG))

    @classmethod
    def angle_to_duration(cls, angle_deg: float, speed: SpeedLevel = "medium") -> float:
        angular_vel = cls.SPEED_MAP[speed]["angular"]
        return abs(math.radians(angle_deg)) / angular_vel


SPEED_MAP = RobotCapabilities.SPEED_MAP
ANGULAR_VEL_DEFAULT = RobotCapabilities.ANGULAR_VEL_DEFAULT
MAX_DURATION_SEC = RobotCapabilities.MAX_DURATION_SEC
MAX_ANGLE_DEG = RobotCapabilities.MAX_ANGLE_DEG
MIN_DURATION_SEC = RobotCapabilities.MIN_DURATION_SEC
EMERGENCY_KEYWORDS = RobotCapabilities.EMERGENCY_KEYWORDS
SPEED_KEYWORDS = RobotCapabilities.SPEED_KEYWORDS
clamp_duration = RobotCapabilities.clamp_duration
clamp_angle = RobotCapabilities.clamp_angle
angle_to_duration = RobotCapabilities.angle_to_duration
