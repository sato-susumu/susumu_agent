"""ツール直接実行デバッガー。LLM を使わずにツールを呼び出してロボットの動作を確認する。

使い方（MockRobot）:
    python3 -m susumu_agent.debug_tools move forward medium 2.0
    python3 -m susumu_agent.debug_tools rotate 90 medium
    python3 -m susumu_agent.debug_tools status
    python3 -m susumu_agent.debug_tools sequence triangle
    python3 -m susumu_agent.debug_tools sequence square

使い方（ROS2 実機 / turtlesim）:
    python3 -m susumu_agent.debug_tools --real move forward medium 2.0
    python3 -m susumu_agent.debug_tools --real --cmd-vel-topic /turtle1/cmd_vel move forward medium 2.0
"""
from __future__ import annotations

import asyncio
import sys


class DebugRunner:
    def __init__(self, args: list[str]) -> None:
        self._args = list(args)
        self._real = False
        self._cmd_vel_topic = "/cmd_vel"
        self._ros_node = None

    def _parse_flags(self) -> None:
        if "--real" in self._args:
            self._real = True
            self._args.remove("--real")
        if "--cmd-vel-topic" in self._args:
            idx = self._args.index("--cmd-vel-topic")
            self._cmd_vel_topic = self._args[idx + 1]
            self._args.pop(idx)
            self._args.pop(idx)

    def _setup_robot(self):
        if self._real:
            from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE, ROS2Robot
            if not ROS2_AVAILABLE:
                print("[ERROR] rclpy が利用できません。--real を外してください。")
                sys.exit(1)
            import rclpy
            if not rclpy.ok():
                rclpy.init()
            self._ros_node = rclpy.create_node("susumu_agent_debug")
            return ROS2Robot(self._ros_node, self._cmd_vel_topic)
        else:
            from susumu_agent.robot.mock_robot import MockRobot
            return MockRobot()

    def _teardown(self) -> None:
        if self._ros_node is not None:
            self._ros_node.destroy_node()
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()

    async def run(self) -> None:
        self._parse_flags()

        from susumu_agent.camera import CameraClient
        from susumu_agent.macro_store import MacroStore
        from susumu_agent.session_store import SessionStore
        from susumu_agent.tools import RobotTools

        robot = self._setup_robot()
        tools = RobotTools(
            robot=robot,
            camera=CameraClient(mode="simulate"),
            session_store=SessionStore(),
            macro_store=MacroStore(),
        )

        if not self._args:
            print(__doc__)
            self._teardown()
            return

        cmd = self._args[0]
        try:
            if cmd == "move":
                direction = self._args[1] if len(self._args) > 1 else "forward"
                speed = self._args[2] if len(self._args) > 2 else "medium"
                duration = float(self._args[3]) if len(self._args) > 3 else 2.0
                print(f"[debug] move_robot({direction!r}, {speed!r}, {duration})")
                result = await tools.move_robot(direction, speed, duration)
                print(f"[result] {result}")

            elif cmd == "rotate":
                angle = float(self._args[1]) if len(self._args) > 1 else 90.0
                speed = self._args[2] if len(self._args) > 2 else "medium"
                print(f"[debug] rotate_robot({angle}, {speed!r})")
                result = await tools.rotate_robot(angle, speed)
                print(f"[result] {result}")

            elif cmd == "stop":
                print("[debug] move_robot('stop', 'medium', 0)")
                result = await tools.move_robot("stop", "medium", 0)
                print(f"[result] {result}")

            elif cmd == "status":
                result = tools.query_status()
                print(f"[result] {result}")

            elif cmd == "sequence":
                shape = self._args[1] if len(self._args) > 1 else "triangle"
                speed = self._args[2] if len(self._args) > 2 else "medium"
                if shape == "triangle":
                    steps = []
                    for _ in range(3):
                        steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
                        steps.append({"type": "rotate", "angle_deg": -120, "speed": speed})
                elif shape == "square":
                    steps = []
                    for _ in range(4):
                        steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
                        steps.append({"type": "rotate", "angle_deg": -90, "speed": speed})
                else:
                    print(f"[ERROR] 不明な shape: {shape}。triangle / square を指定してください。")
                    self._teardown()
                    return
                print(f"[debug] execute_sequence({shape}, {len(steps)} steps)")
                result = await tools.execute_sequence(steps)
                print(f"[result] {result}")

            else:
                print(f"[ERROR] 不明なコマンド: {cmd}")
                print(__doc__)

        finally:
            self._teardown()


def main():
    asyncio.run(DebugRunner(sys.argv[1:]).run())


if __name__ == "__main__":
    main()
