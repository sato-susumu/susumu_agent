from __future__ import annotations

import asyncio

from susumu_agent.business.capabilities import SPEED_MAP, angle_to_duration, clamp_angle, clamp_duration
from susumu_agent.business.shared_state import get_state

from .interface import Direction, RobotInterface, SpeedLevel, TurnDirection

try:
    import rclpy  # noqa: F401
    from geometry_msgs.msg import Twist, TwistStamped
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False


class ROS2Robot(RobotInterface):
    """実機向け ROS2 実装。rclpy が必要。"""

    def __init__(
        self,
        node: "Node",
        cmd_vel_topic: str = "/cmd_vel",
        cmd_vel_stamped: bool = False,
    ):
        if not ROS2_AVAILABLE:
            raise RuntimeError("rclpy が利用できません。simulate モードを使用してください。")
        self._node = node
        self._cmd_vel_stamped = cmd_vel_stamped
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        msg_cls = TwistStamped if self._cmd_vel_stamped else Twist
        self._pub = node.create_publisher(msg_cls, cmd_vel_topic, qos)

    def _publish(self, linear_x: float, angular_z: float) -> None:
        if self._cmd_vel_stamped:
            msg = TwistStamped()
            msg.header.stamp = self._node.get_clock().now().to_msg()
            msg.twist.linear.x = linear_x
            msg.twist.angular.z = angular_z
        else:
            msg = Twist()
            msg.linear.x = linear_x
            msg.angular.z = angular_z
        self._pub.publish(msg)

    async def move(self, direction: Direction, speed: SpeedLevel, duration_sec: float) -> None:
        linear = SPEED_MAP[speed]["linear"]
        if direction == "backward":
            linear = -linear
        elif direction == "stop":
            linear = 0.0

        state = get_state()

        if direction == "stop":
            self._publish(0.0, 0.0)
            state.zero_twist()
            return

        continuous = (duration_sec == 0.0)
        if not continuous:
            duration_sec = clamp_duration(duration_sec)

        state.set_twist(linear, 0.0)
        interval = 0.1
        elapsed = 0.0
        while (continuous or elapsed < duration_sec) and not state.stop_event.is_set():
            self._publish(linear, 0.0)
            await asyncio.sleep(interval)
            elapsed += interval
        self._publish(0.0, 0.0)
        state.zero_twist()

    async def rotate(self, angle_deg: float, speed: SpeedLevel, continuous: bool = False) -> None:
        angular = SPEED_MAP[speed]["angular"]
        if angle_deg < 0:
            angular = -angular

        if continuous:
            state = get_state()
            state.set_twist(0.0, angular)
            interval = 0.1
            while not state.stop_event.is_set():
                self._publish(0.0, angular)
                await asyncio.sleep(interval)
            self._publish(0.0, 0.0)
            state.zero_twist()
            return

        angle_deg = clamp_angle(angle_deg)
        duration_sec = angle_to_duration(angle_deg, speed)

        state = get_state()
        state.set_twist(0.0, angular)
        interval = 0.1
        elapsed = 0.0
        while elapsed < duration_sec and not state.stop_event.is_set():
            self._publish(0.0, angular)
            await asyncio.sleep(interval)
            elapsed += interval
        self._publish(0.0, 0.0)
        state.zero_twist()

    async def curve(self, direction: Direction, turn: TurnDirection, speed: SpeedLevel, duration_sec: float) -> None:
        linear = SPEED_MAP[speed]["linear"]
        if direction == "backward":
            linear = -linear
        angular = SPEED_MAP[speed]["angular"] * 0.5
        if turn == "right":
            angular = -angular

        state = get_state()
        continuous = (duration_sec == 0.0)
        if not continuous:
            duration_sec = clamp_duration(duration_sec)

        state.set_twist(linear, angular)
        interval = 0.1
        elapsed = 0.0
        while (continuous or elapsed < duration_sec) and not state.stop_event.is_set():
            self._publish(linear, angular)
            await asyncio.sleep(interval)
            elapsed += interval
        self._publish(0.0, 0.0)
        state.zero_twist()

    def stop(self) -> None:
        self._publish(0.0, 0.0)
        get_state().zero_twist()

    def get_status(self) -> dict:
        state = get_state()
        twist = state.get_twist()
        return {
            "is_active": state.is_active,
            "linear_x": twist.linear_x,
            "angular_z": twist.angular_z,
        }
