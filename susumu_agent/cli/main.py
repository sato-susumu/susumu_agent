"""自然言語ロボット制御システム エントリポイント。

simulate / dry_run モードでは ROS2 不要で動作確認できる。
"""
from __future__ import annotations

import asyncio
import datetime
import importlib.util
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import click
import yaml
from loguru import logger

from susumu_agent.agent.factory import AgentFactory
from susumu_agent.sensors.camera import CameraClient
from susumu_agent.business.capabilities import EMERGENCY_KEYWORDS
from susumu_agent.storage.macro_store import MacroStore
from susumu_agent.robot.mock_robot import MockRobot
from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE
from susumu_agent.logging.ros_logger import setup_loguru
from susumu_agent.storage.session_store import SessionStore
from susumu_agent.business.shared_state import get_state
from susumu_agent.agent.tools import RobotTools
try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False

from google.adk.agents import LlmAgent  # noqa: F401
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part


class RobotController:
    _WELCOME_MSG = """
╔══════════════════════════════════════════════════╗
║       ロボット制御システム 起動しました            ║
╠══════════════════════════════════════════════════╣
║ できること:                                       ║
║   前進・後退・停止・旋回・シーケンス・カメラ確認    ║
║ 例:                                              ║
║   「ゆっくり前進」「右向いて」「三角形を描いて」    ║
║   「何が見える？」「パトロールを登録して」          ║
║ 緊急停止: 「ストップ」と入力                       ║
║ 終了: Ctrl+C                                     ║
╚══════════════════════════════════════════════════╝
"""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._robot = None
        self._ros_node = None
        self._tools = None
        self._agent = None
        self._session_service = None
        self._session_id = "session_001"
        self._ros_spin_thread = None
        self._ros_input_queue = None
        self._ros_loop = None
        self._to_human_pub = None
        self._agent_event_pub = None
        self._from_human_sub = None

    @classmethod
    def _load_config(cls, path: str = "config.yaml") -> dict:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    def _is_emergency(self, text: str) -> bool:
        normalized = text.strip().lower()
        return any(kw.lower() in normalized for kw in EMERGENCY_KEYWORDS)

    def _is_help(self, text: str) -> bool:
        return text.strip() in {"ヘルプ", "help", "何ができる", "使い方", "?", "？"}

    def _uses_ros_topics(self) -> bool:
        return self._config.get("interface", {}).get("input_mode") == "ros2"

    # ------------------------------------------------------------------ setup

    def _setup_robot(self) -> None:
        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")

        if mode == "real" or self._uses_ros_topics():
            if ROS2_AVAILABLE:
                import rclpy  # noqa: PLC0415

                if not rclpy.ok():
                    rclpy.init()
                self._ros_node = rclpy.create_node("susumu_agent_robot")
            elif self._uses_ros_topics():
                raise RuntimeError("ROS2 topic 入出力には rclpy / std_msgs が必要です。")

        if mode == "real":
            if ROS2_AVAILABLE:
                from susumu_agent.robot.ros2_robot import ROS2Robot  # noqa: PLC0415

                self._robot = ROS2Robot(
                    self._ros_node,
                    robot_cfg.get("cmd_vel_topic", "/cmd_vel"),
                    _as_bool(robot_cfg.get("cmd_vel_stamped", True)),
                )
                return
            logger.warning("ROS2 が利用できません。simulate モードに切り替えます。")
            self._config["robot"]["mode"] = "simulate"

        self._robot = MockRobot(dry_run=(mode == "dry_run"))

    def _setup_tools(self) -> None:
        robot_cfg = self._config.get("robot", {})
        camera = CameraClient(
            image_topic=robot_cfg.get("image_topic", "/camera/image_raw"),
            mode=robot_cfg.get("mode", "simulate"),
        )
        self._tools = RobotTools(
            robot=self._robot,
            camera=camera,
            session_store=SessionStore(),
            macro_store=MacroStore(),
        )
    async def _setup_adk(self) -> None:
        self._agent = AgentFactory(self._config).create_agent(
            self._tools.get_all_tools(), tools_instance=self._tools
        )
        self._session_service = InMemorySessionService()
        await self._session_service.create_session(
            app_name="robot_nl", user_id="operator", session_id=self._session_id
        )
        logger.info(f"ADK エージェント起動（モデル: {self._config['llm']['model']}）")

    # ------------------------------------------------------------------ ADK runner

    async def _run_with_adk(
        self,
        user_input: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        runner = Runner(agent=self._agent, session_service=self._session_service, app_name="robot_nl")
        content = Content(role="user", parts=[Part(text=user_input)])
        result_text = ""
        announced = False
        observed = False
        async for event in runner.run_async(
            user_id="operator", session_id=self._session_id, new_message=content,
        ):
            if not event.content:
                continue
            func_calls = event.get_function_calls()
            if any(fc.name == "observe" for fc in func_calls):
                observed = True
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    result_text += part.text
                    if not announced and on_text is not None and func_calls:
                        on_text(part.text)
                        announced = True
            if event.is_final_response() and observed and on_text is not None:
                final_text = result_text.strip()
                if final_text:
                    on_text(final_text)
        return result_text

    def _setup_ros_topic_io(self, loop: asyncio.AbstractEventLoop) -> None:
        if not self._uses_ros_topics():
            return
        if self._ros_node is None:
            raise RuntimeError("ROS2 node が初期化されていません。")

        import rclpy  # noqa: PLC0415
        from std_msgs.msg import String  # noqa: PLC0415

        interface_cfg = self._config.get("interface", {})
        from_topic = interface_cfg.get("from_human_topic", "/from_human")
        to_topic = interface_cfg.get("to_human_topic", "/to_human")
        agent_event_topic = interface_cfg.get("agent_event_topic", "/agent_event")
        self._ros_loop = loop
        self._ros_input_queue = asyncio.Queue()
        self._to_human_pub = self._ros_node.create_publisher(String, to_topic, 10)
        self._agent_event_pub = self._ros_node.create_publisher(String, agent_event_topic, 10)

        def _on_from_human(msg: String) -> None:
            text = msg.data.strip()
            if not text or self._ros_input_queue is None or self._ros_loop is None:
                return
            logger.info(f"[/from_human] {text}")
            if self._is_emergency(text) and self._robot is not None:
                get_state().stop_event.set()
                self._robot.stop()
            self._ros_loop.call_soon_threadsafe(self._ros_input_queue.put_nowait, text)

        self._from_human_sub = self._ros_node.create_subscription(String, from_topic, _on_from_human, 10)
        self._ros_spin_thread = threading.Thread(target=self._spin_ros_node, daemon=True)
        self._ros_spin_thread.start()
        logger.info(f"ROS2 入力: {from_topic} (std_msgs/String)")
        logger.info(f"ROS2 応答: {to_topic} (std_msgs/String)")
        logger.info(f"エージェントイベント: {agent_event_topic} (std_msgs/String)")

    def _spin_ros_node(self) -> None:
        import rclpy  # noqa: PLC0415
        from rclpy.executors import ExternalShutdownException  # noqa: PLC0415

        try:
            rclpy.spin(self._ros_node)
        except ExternalShutdownException:
            pass

    def _publish_to_human(self, text: str) -> None:
        if self._to_human_pub is None:
            return
        from std_msgs.msg import String  # noqa: PLC0415

        logger.info(f"[/to_human] {text}")
        self._to_human_pub.publish(String(data=text))

    def _publish_agent_event(self, event: dict) -> None:
        if self._agent_event_pub is None:
            return
        from std_msgs.msg import String  # noqa: PLC0415

        payload = json.dumps(event, ensure_ascii=False)
        logger.info(f"[/agent_event] {payload}")
        self._agent_event_pub.publish(String(data=payload))

    # ------------------------------------------------------------------ main loop

    async def _handle_input(
        self,
        user_input: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        if self._agent is None or self._session_service is None:
            raise RuntimeError("ADK エージェントが初期化されていません。")
        return await asyncio.wait_for(
            self._run_with_adk(user_input, on_text=on_text),
            timeout=self._config["llm"].get("timeout_sec", 5),
        )

    def _print_startup(self) -> None:
        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")
        mode_label = {"real": "実機", "simulate": "シミュレーション", "dry_run": "ドライラン"}.get(mode, mode)
        model_name = self._config.get("llm", {}).get("model", "不明")
        logger.info("\n" + self._WELCOME_MSG)
        logger.info(f"モード: {mode_label} | LLM: ADK ({model_name})")

    def _shutdown(self) -> None:
        state = get_state()
        logger.info("終了します...")
        state.shutdown_event.set()
        state.stop_event.set()
        if self._robot is not None:
            self._robot.stop()
        if self._ros_node is not None:
            import rclpy  # noqa: PLC0415
            if rclpy.ok():
                rclpy.shutdown()
        if self._ros_spin_thread is not None:
            self._ros_spin_thread.join(timeout=1.0)
        if self._ros_node is not None:
            self._ros_node.destroy_node()

    async def _process_user_input(
        self,
        user_input: str,
        session_store: SessionStore,
        state,
        on_text: Callable[[str], None] | None = None,
    ) -> str | None:
        state.stop_event.clear()
        if self._is_help(user_input):
            logger.info("\n" + self._WELCOME_MSG)
            return self._WELCOME_MSG
        if self._is_emergency(user_input):
            state.stop_event.set()
            if self._robot is not None:
                self._robot.stop()
            logger.warning("緊急停止しました。")
            session_store.save_turn("user", user_input)
            session_store.save_turn("assistant", "停止しました。")
            return "停止しました。"

        logger.info("考え中...")
        session_store.save_turn("user", user_input)

        try:
            response = await self._handle_input(user_input, on_text=on_text)
        except asyncio.TimeoutError:
            response = "タイムアウトしました。もう一度お試しください。"
            logger.error(response)
        except Exception as e:
            response = f"エラーが発生しました: {e}"
            logger.error(response)

        session_store.save_turn("assistant", response)
        return response

    async def _run_stdin_loop(self) -> None:
        session_store = SessionStore()
        state = get_state()
        while True:
            try:
                user_input = input("あなた: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            await self._process_user_input(user_input, session_store, state)

    async def _run_ros_topic_loop(self) -> None:
        if self._ros_input_queue is None:
            raise RuntimeError("ROS2 topic 入力キューが初期化されていません。")
        session_store = SessionStore()
        state = get_state()

        loop = asyncio.get_running_loop()

        def _on_agent_event(event: dict) -> None:
            loop.call_soon_threadsafe(
                lambda: self._publish_agent_event(event)
            )

        if self._tools is not None:
            self._tools.set_agent_event_callback(_on_agent_event)

        while not state.shutdown_event.is_set():
            user_input = await self._ros_input_queue.get()
            response = await self._process_user_input(
                user_input, session_store, state,
                on_text=self._publish_to_human,
            )
            if response:
                self._publish_agent_event({"type": "action_completed", "response": response})

    async def run(self) -> None:
        try:
            self._setup_robot()
            self._setup_tools()
            await self._setup_adk()
            self._setup_ros_topic_io(asyncio.get_running_loop())
            self._print_startup()

            if self._uses_ros_topics():
                await self._run_ros_topic_loop()
            else:
                await self._run_stdin_loop()

        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()


# ------------------------------------------------------------------ entry points

def _setup_logging(debug: bool, debug_dir: str) -> None:
    if debug:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        setup_loguru(str(Path(debug_dir) / f"{ts}_susumu_agent.log"))
        SessionStore().set_debug_dir(debug_dir)
    else:
        logger.remove()
        logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")


def _load_dotenv(env_file: str | None) -> None:
    if not _DOTENV_AVAILABLE:
        return
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=False)


def _read_ros2_params() -> dict:
    """ROS2 launch パラメータを読み取って dict で返す。ROS2 なし環境では空 dict。"""
    if importlib.util.find_spec("rclpy") is None:
        return {}
    import rclpy  # noqa: PLC0415
    rclpy.init()
    node = rclpy.create_node("susumu_agent_node")
    node.declare_parameter("config_path", "")
    node.declare_parameter("robot_mode", "")
    node.declare_parameter("cmd_vel_stamped", False)
    node.declare_parameter("from_human_topic", "/from_human")
    node.declare_parameter("to_human_topic", "/to_human")
    node.declare_parameter("env_file", "")
    node.declare_parameter("debug", False)
    node.declare_parameter("debug_dir", "debug")
    raw_debug = node.get_parameter("debug").value
    raw_cmd_vel_stamped = node.get_parameter("cmd_vel_stamped").value
    params = {
        "config_path": node.get_parameter("config_path").value or None,
        "robot_mode": node.get_parameter("robot_mode").value or None,
        "cmd_vel_stamped": raw_cmd_vel_stamped,
        "from_human_topic": node.get_parameter("from_human_topic").value or "/from_human",
        "to_human_topic": node.get_parameter("to_human_topic").value or "/to_human",
        "env_file": node.get_parameter("env_file").value or None,
        "debug": raw_debug if isinstance(raw_debug, bool) else str(raw_debug).lower() == "true",
        "debug_dir": node.get_parameter("debug_dir").value or "debug",
    }
    node.destroy_node()
    rclpy.shutdown()
    return params


def _build_config(
    config_path: str,
    robot_mode: str | None,
    cmd_vel_stamped: bool | str | None = None,
    input_mode: str | None = None,
    from_human_topic: str | None = None,
    to_human_topic: str | None = None,
) -> dict:
    config = RobotController._load_config(config_path)
    if robot_mode:
        config.setdefault("robot", {})["mode"] = robot_mode
    if cmd_vel_stamped is not None:
        config.setdefault("robot", {})["cmd_vel_stamped"] = _as_bool(cmd_vel_stamped)
    if input_mode:
        config.setdefault("interface", {})["input_mode"] = input_mode
    if from_human_topic:
        config.setdefault("interface", {})["from_human_topic"] = from_human_topic
    if to_human_topic:
        config.setdefault("interface", {})["to_human_topic"] = to_human_topic
    return config


def _as_bool(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main_entry() -> None:
    """ROS2 console_scripts エントリポイント。"""
    p = _read_ros2_params()
    _load_dotenv(p.get("env_file"))
    _setup_logging(p.get("debug", False), p.get("debug_dir", "debug"))
    config = _build_config(
        p.get("config_path") or "config.yaml",
        p.get("robot_mode"),
        p.get("cmd_vel_stamped"),
        input_mode="ros2",
        from_human_topic=p.get("from_human_topic"),
        to_human_topic=p.get("to_human_topic"),
    )
    try:
        asyncio.run(RobotController(config).run())
    except KeyboardInterrupt:
        pass


@click.command()
@click.argument("config_path", default="config.yaml", metavar="CONFIG")
@click.option("--robot-mode", default=None, help="robot.mode を上書き（real / simulate / dry_run）")
@click.option("--env-file", default=None, help=".env ファイルのパス")
@click.option("--debug", is_flag=True, default=False, help="デバッグログを debug/ に保存")
@click.option("--debug-dir", default="debug", show_default=True, help="デバッグ出力先ディレクトリ")
def cli(
    config_path: str,
    robot_mode: str | None,
    env_file: str | None,
    debug: bool,
    debug_dir: str,
) -> None:
    """自然言語でロボットを制御する。"""
    _load_dotenv(env_file)
    _setup_logging(debug, debug_dir)
    config = _build_config(config_path, robot_mode)
    try:
        asyncio.run(RobotController(config).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
