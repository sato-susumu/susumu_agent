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


def _setup_robot(real: bool, cmd_vel_topic: str):
    if real:
        from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE, ROS2Robot
        if not ROS2_AVAILABLE:
            print("[ERROR] rclpy が利用できません。--real を外してください。")
            sys.exit(1)
        import rclpy
        if not rclpy.ok():
            rclpy.init()
        node = rclpy.create_node("susumu_agent_debug")
        robot = ROS2Robot(node, cmd_vel_topic)
        return robot, node
    else:
        from susumu_agent.robot.mock_robot import MockRobot
        return MockRobot(), None


async def _run(args: list[str]) -> None:
    real = "--real" in args
    if real:
        args.remove("--real")

    cmd_vel_topic = "/cmd_vel"
    if "--cmd-vel-topic" in args:
        idx = args.index("--cmd-vel-topic")
        cmd_vel_topic = args[idx + 1]
        args.pop(idx)
        args.pop(idx)

    import susumu_agent.tools as tools_module
    from susumu_agent.camera import CameraClient

    robot, ros_node = _setup_robot(real, cmd_vel_topic)
    tools_module.set_robot(robot)
    tools_module.set_camera(CameraClient(mode="simulate"))

    if not args:
        print(__doc__)
        return

    cmd = args[0]

    try:
        if cmd == "move":
            direction = args[1] if len(args) > 1 else "forward"
            speed = args[2] if len(args) > 2 else "medium"
            duration = float(args[3]) if len(args) > 3 else 2.0
            print(f"[debug] move_robot({direction!r}, {speed!r}, {duration})")
            result = await tools_module.move_robot(direction, speed, duration)
            print(f"[result] {result}")

        elif cmd == "rotate":
            angle = float(args[1]) if len(args) > 1 else 90.0
            speed = args[2] if len(args) > 2 else "medium"
            print(f"[debug] rotate_robot({angle}, {speed!r})")
            result = await tools_module.rotate_robot(angle, speed)
            print(f"[result] {result}")

        elif cmd == "stop":
            print("[debug] move_robot('stop', 'medium', 0)")
            result = await tools_module.move_robot("stop", "medium", 0)
            print(f"[result] {result}")

        elif cmd == "status":
            result = tools_module.query_status()
            print(f"[result] {result}")

        elif cmd == "sequence":
            shape = args[1] if len(args) > 1 else "triangle"
            speed = args[2] if len(args) > 2 else "medium"
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
                return
            print(f"[debug] execute_sequence({shape}, {len(steps)} steps)")
            result = await tools_module.execute_sequence(steps)
            print(f"[result] {result}")

        else:
            print(f"[ERROR] 不明なコマンド: {cmd}")
            print(__doc__)

    finally:
        if ros_node is not None:
            ros_node.destroy_node()
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()


def main():
    args = sys.argv[1:]
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
