from __future__ import annotations

import asyncio

from loguru import logger

from susumu_agent.business.capabilities import SPEED_MAP, angle_to_duration, clamp_angle, clamp_duration
from susumu_agent.business.shared_state import get_state

from .interface import Direction, RobotInterface, SpeedLevel


class MockRobot(RobotInterface):
    """ROS2 なしで動作確認できるモック実装。端末に動作を表示する。"""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run

    async def move(self, direction: Direction, speed: SpeedLevel, duration_sec: float) -> None:
        linear = SPEED_MAP[speed]["linear"]
        if direction == "backward":
            linear = -linear
        elif direction == "stop":
            linear = 0.0

        duration_sec = clamp_duration(duration_sec)
        state = get_state()

        if direction == "stop":
            logger.info("[MockRobot] 停止")
            if not self._dry_run:
                state.zero_twist()
            return

        logger.info(f"[MockRobot] {direction} linear_x={linear:.2f} m/s × {duration_sec:.1f}s 開始")
        if not self._dry_run:
            state.set_twist(linear, 0.0)

        interval = 0.1
        elapsed = 0.0
        while elapsed < duration_sec and not state.stop_event.is_set():
            await asyncio.sleep(interval)
            elapsed += interval

        logger.info(f"[MockRobot] {direction} 完了 → 停止")
        if not self._dry_run:
            state.zero_twist()

    async def rotate(self, angle_deg: float, speed: SpeedLevel) -> None:
        angle_deg = clamp_angle(angle_deg)
        angular = SPEED_MAP[speed]["angular"]
        if angle_deg < 0:
            angular = -angular
        duration_sec = angle_to_duration(angle_deg, speed)

        logger.info(f"[MockRobot] rotate angle={angle_deg:.1f}° angular_z={angular:.2f} rad/s × {duration_sec:.2f}s 開始")
        state = get_state()
        if not self._dry_run:
            state.set_twist(0.0, angular)

        interval = 0.1
        elapsed = 0.0
        while elapsed < duration_sec and not state.stop_event.is_set():
            await asyncio.sleep(interval)
            elapsed += interval

        logger.info("[MockRobot] rotate 完了 → 停止")
        if not self._dry_run:
            state.zero_twist()

    def stop(self) -> None:
        logger.warning("[MockRobot] 緊急停止")
        if not self._dry_run:
            get_state().zero_twist()

    def get_status(self) -> dict:
        state = get_state()
        twist = state.get_twist()
        return {
            "is_active": state.is_active,
            "linear_x": twist.linear_x,
            "angular_z": twist.angular_z,
        }
