from __future__ import annotations
import asyncio
import time
from .interface import RobotInterface, Direction, SpeedLevel
from capabilities import SPEED_MAP, angle_to_duration, clamp_duration
from shared_state import get_state


class MockRobot(RobotInterface):
    """ROS2 なしで動作確認できるモック実装。端末に動作を表示する。"""

    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run  # True の場合は表示のみ・SharedState も更新しない

    async def move(self, direction: Direction, speed: SpeedLevel, duration_sec: float) -> None:
        linear = SPEED_MAP[speed]["linear"]
        if direction == "backward":
            linear = -linear
        elif direction == "stop":
            linear = 0.0

        duration_sec = clamp_duration(duration_sec)
        state = get_state()

        if direction == "stop":
            print(f"  [MockRobot] 停止")
            if not self._dry_run:
                state.zero_twist()
            return

        print(f"  [MockRobot] {direction} linear_x={linear:.2f} m/s × {duration_sec:.1f}s 開始")
        if not self._dry_run:
            state.set_twist(linear, 0.0)

        await asyncio.sleep(duration_sec)

        print(f"  [MockRobot] {direction} 完了 → 停止")
        if not self._dry_run:
            state.zero_twist()

    async def rotate(self, angle_deg: float, speed: SpeedLevel) -> None:
        from capabilities import clamp_angle
        angle_deg = clamp_angle(angle_deg)
        angular = SPEED_MAP[speed]["angular"]
        if angle_deg < 0:
            angular = -angular
        duration_sec = angle_to_duration(angle_deg, speed)

        print(f"  [MockRobot] rotate angle={angle_deg:.1f}° angular_z={angular:.2f} rad/s × {duration_sec:.2f}s 開始")
        state = get_state()
        if not self._dry_run:
            state.set_twist(0.0, angular)

        await asyncio.sleep(duration_sec)

        print(f"  [MockRobot] rotate 完了 → 停止")
        if not self._dry_run:
            state.zero_twist()

    def stop(self) -> None:
        print(f"  [MockRobot] 緊急停止")
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
