"""ツール直接実行デバッガー。LLM を使わずにツールを呼び出してロボットの動作を確認する。"""
from __future__ import annotations

import asyncio
import sys

import click
from loguru import logger

from susumu_agent.agent.tools import RobotTools
from susumu_agent.robot.mock_robot import MockRobot
from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE, ROS2Robot
from susumu_agent.sensors.camera import CameraClient
from susumu_agent.storage.macro_store import MacroStore
from susumu_agent.storage.session_store import SessionStore


class DebugRunner:
    def __init__(self, real: bool, cmd_vel_topic: str) -> None:
        self._real = real
        self._cmd_vel_topic = cmd_vel_topic
        self._ros_node = None

    def _setup_robot(self):
        if self._real:
            if not ROS2_AVAILABLE:
                logger.error("rclpy が利用できません。--real を外してください。")
                sys.exit(1)
            import rclpy
            if not rclpy.ok():
                rclpy.init()
            self._ros_node = rclpy.create_node("susumu_agent_debug")
            return ROS2Robot(self._ros_node, self._cmd_vel_topic)
        return MockRobot()

    def _teardown(self) -> None:
        if self._ros_node is not None:
            self._ros_node.destroy_node()
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()

    def _build_tools(self, robot):
        return RobotTools(
            robot=robot,
            camera=CameraClient(mode="simulate"),
            session_store=SessionStore(),
            macro_store=MacroStore(),
        )

    async def run_move(self, direction: str, speed: str, duration: float) -> None:
        robot = self._setup_robot()
        tools = self._build_tools(robot)
        try:
            logger.debug(f"move_robot({direction!r}, {speed!r}, {duration})")
            logger.info(f"result: {await tools.move_robot(direction, speed, duration)}")
        finally:
            self._teardown()

    async def run_rotate(self, angle: float, speed: str, duration: float) -> None:
        robot = self._setup_robot()
        tools = self._build_tools(robot)
        try:
            logger.debug(f"rotate_robot({angle}, {speed!r}, duration_sec={duration})")
            logger.info(f"result: {await tools.rotate_robot(angle, speed, duration_sec=duration)}")
        finally:
            self._teardown()

    async def run_stop(self) -> None:
        robot = self._setup_robot()
        tools = self._build_tools(robot)
        try:
            logger.debug("move_robot('stop', 'medium', 0)")
            logger.info(f"result: {await tools.move_robot('stop', 'medium', 0)}")
        finally:
            self._teardown()

    async def run_status(self) -> None:
        robot = self._setup_robot()
        tools = self._build_tools(robot)
        try:
            logger.info(f"result: {tools.query_status()}")
        finally:
            self._teardown()

    async def run_sequence(self, shape: str, speed: str) -> None:
        robot = self._setup_robot()
        tools = self._build_tools(robot)
        try:
            if shape == "triangle":
                steps = [s for _ in range(3) for s in [
                    {"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0},
                    {"type": "rotate", "angle_deg": -120, "speed": speed},
                ]]
            elif shape == "square":
                steps = [s for _ in range(4) for s in [
                    {"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0},
                    {"type": "rotate", "angle_deg": -90, "speed": speed},
                ]]
            else:
                logger.error(f"不明な shape: {shape}。triangle / square を指定してください。")
                return
            logger.debug(f"execute_sequence({shape}, {len(steps)} steps)")
            logger.info(f"result: {await tools.execute_sequence(steps)}")
        finally:
            self._teardown()


@click.group()
@click.option("--real", is_flag=True, default=False, help="ROS2 実機に接続する")
@click.option("--cmd-vel-topic", default="/cmd_vel", show_default=True, help="cmd_vel トピック名")
@click.pass_context
def cli(ctx: click.Context, real: bool, cmd_vel_topic: str) -> None:
    """LLM を使わずにロボットツールを直接テストする CLI。"""
    ctx.ensure_object(dict)
    ctx.obj["runner"] = DebugRunner(real=real, cmd_vel_topic=cmd_vel_topic)


@cli.command()
@click.argument("direction", type=click.Choice(["forward", "backward", "stop"]))
@click.argument("speed", type=click.Choice(["low", "medium", "high"]), default="medium")
@click.argument("duration", type=float, default=2.0)
@click.pass_context
def move(ctx: click.Context, direction: str, speed: str, duration: float) -> None:
    """ロボットを移動させる。"""
    asyncio.run(ctx.obj["runner"].run_move(direction, speed, duration))


@cli.command()
@click.argument("angle", type=float, default=90.0)
@click.argument("speed", type=click.Choice(["low", "medium", "high"]), default="medium")
@click.option("--duration", type=float, default=0.0, show_default=True,
              help="旋回継続時間（秒）。指定時は angle の符号のみ方向に使用")
@click.pass_context
def rotate(ctx: click.Context, angle: float, speed: str, duration: float) -> None:
    """ロボットを旋回させる（正=左回り、負=右回り）。"""
    asyncio.run(ctx.obj["runner"].run_rotate(angle, speed, duration))


@cli.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """ロボットを停止させる。"""
    asyncio.run(ctx.obj["runner"].run_stop())


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """現在の移動状態を確認する。"""
    asyncio.run(ctx.obj["runner"].run_status())


@cli.command()
@click.argument("shape", type=click.Choice(["triangle", "square"]), default="triangle")
@click.argument("speed", type=click.Choice(["low", "medium", "high"]), default="medium")
@click.pass_context
def sequence(ctx: click.Context, shape: str, speed: str) -> None:
    """シーケンス移動を実行する（triangle / square）。"""
    asyncio.run(ctx.obj["runner"].run_sequence(shape, speed))


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")
    cli()


if __name__ == "__main__":
    main()
