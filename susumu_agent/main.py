"""自然言語ロボット制御システム エントリポイント。

simulate / dry_run モードでは ROS2 不要で動作確認できる。
"""
from __future__ import annotations

import asyncio
import datetime
import importlib.util
import re
import sys
from pathlib import Path

import click
import yaml
from loguru import logger

from susumu_agent.agent import AgentFactory
from susumu_agent.camera import CameraClient
from susumu_agent.capabilities import EMERGENCY_KEYWORDS
from susumu_agent.macro_store import MacroStore
from susumu_agent.robot.mock_robot import MockRobot
from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE
from susumu_agent.ros_logger import setup_loguru
from susumu_agent.session_store import SessionStore
from susumu_agent.shared_state import get_state
from susumu_agent.tools import RobotTools
from susumu_agent.watchdog import Watchdog

try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False

ADK_AVAILABLE = False
try:
    from google.adk.agents import LlmAgent  # noqa: F401
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part
    ADK_AVAILABLE = True
except ImportError:
    Content = None  # type: ignore[assignment,misc]
    Part = None  # type: ignore[assignment,misc]


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
    _SPEED_MAP_REF = {"low": 0.1, "medium": 0.3, "high": 0.5}

    def __init__(self, config: dict) -> None:
        self._config = config
        self._robot = None
        self._ros_node = None
        self._tools = None
        self._agent = None
        self._session_service = None
        self._session_id = "session_001"
        self._use_adk = False

    @classmethod
    def _load_config(cls, path: str = "config.yaml") -> dict:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    def _is_emergency(self, text: str) -> bool:
        normalized = text.strip().lower()
        return any(kw.lower() in normalized for kw in EMERGENCY_KEYWORDS)

    def _is_help(self, text: str) -> bool:
        return text.strip() in {"ヘルプ", "help", "何ができる", "使い方", "?", "？"}

    # ------------------------------------------------------------------ setup

    def _setup_robot(self) -> None:
        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")

        if mode == "real":
            if ROS2_AVAILABLE:
                import rclpy  # noqa: PLC0415

                from susumu_agent.robot.ros2_robot import ROS2Robot  # noqa: PLC0415
                if not rclpy.ok():
                    rclpy.init()
                self._ros_node = rclpy.create_node("susumu_agent_robot")
                self._robot = ROS2Robot(self._ros_node, robot_cfg.get("cmd_vel_topic", "/cmd_vel"))
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
        Watchdog(timeout_sec=robot_cfg.get("watchdog_timeout_sec", 5.0)).start()

    async def _setup_adk(self) -> None:
        if not ADK_AVAILABLE:
            return
        try:
            self._agent = AgentFactory(self._config).create_agent(
                self._tools.get_all_tools(), tools_instance=self._tools
            )
            self._session_service = InMemorySessionService()
            await self._session_service.create_session(
                app_name="robot_nl", user_id="operator", session_id=self._session_id
            )
            self._use_adk = True
            logger.info(f"ADK エージェント起動（モデル: {self._config['llm']['model']}）")
        except Exception as e:
            logger.error(f"ADK 初期化失敗: {e}\nシミュレーションモードで起動します。")

    # ------------------------------------------------------------------ ADK runner

    async def _run_with_adk(self, user_input: str) -> str:
        runner = Runner(agent=self._agent, session_service=self._session_service, app_name="robot_nl")
        content = Content(role="user", parts=[Part(text=user_input)])
        result_text = ""
        async for event in runner.run_async(
            user_id="operator", session_id=self._session_id, new_message=content,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        result_text += part.text
        return result_text

    # ------------------------------------------------------------------ rule-based fallback

    def _parse_speed(self, text: str) -> str:
        if any(w in text for w in ["ゆっくり", "ゆったり", "そろそろ", "ちょっとずつ"]):
            return "low"
        if any(w in text for w in ["素早く", "速く", "全力", "ダッシュ"]):
            return "high"
        return "medium"

    def _parse_duration(self, text: str, speed: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
        if m:
            return float(m.group(1))
        dist_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:メートル|m)\b", text)
        if dist_m:
            return float(dist_m.group(1)) / self._SPEED_MAP_REF[speed]
        dist_cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:センチ|cm)\b", text)
        if dist_cm:
            return float(dist_cm.group(1)) / 100 / self._SPEED_MAP_REF[speed]
        return 2.0

    async def _handle_move(self, direction: str, speed: str, duration: float) -> str:
        result = await self._tools.move_robot(direction, speed, duration)
        label = "前進" if direction == "forward" else "後退"
        return f"{label}しました（{result['linear_x']} m/s、{result['duration_sec']} 秒）"

    async def _handle_rotate(self, text: str, speed: str) -> str:
        angle_m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
        if "右" in text:
            angle = -float(angle_m.group(1)) if angle_m else -90.0
            result = await self._tools.rotate_robot(angle, speed)
            return f"右に{abs(angle):.0f}度旋回しました（{result['duration_sec']} 秒）"
        angle = float(angle_m.group(1)) if angle_m else 90.0
        result = await self._tools.rotate_robot(angle, speed)
        return f"左に{angle:.0f}度旋回しました（{result['duration_sec']} 秒）"

    async def _handle_sequence(self, shape: str, speed: str) -> str:
        if shape == "triangle":
            sides, angle = 3, -120
            label = "三角形"
        else:
            sides, angle = 4, -90
            label = "四角形"
        steps = []
        for _ in range(sides):
            steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
            steps.append({"type": "rotate", "angle_deg": angle, "speed": speed})
        result = await self._tools.execute_sequence(steps)
        return f"{label}を描きました（{result['completed_steps']}/{result['total']} ステップ完了）"

    async def _handle_macro_register(self, text: str) -> str:
        last = self._tools.query_last_command()
        if last["status"] == "none":
            return "登録できるコマンドがありません。先に何か動かしてください。"
        name_m = re.search(r"[「『](.+?)[」』]", text)
        name = name_m.group(1) if name_m else "マクロ1"
        result = await self._tools.manage_macro("register", name, [last["last_command"]])
        return result["message"]

    async def _run_simulate(self, user_input: str) -> str:
        text = user_input.strip()
        speed = self._parse_speed(text)
        duration = self._parse_duration(text, speed)

        if any(w in text for w in ["前進", "前に", "前へ", "まえ", "go", "forward"]):
            return await self._handle_move("forward", speed, duration)
        if any(w in text for w in ["後退", "バック", "うしろ", "後ろ", "backward", "back"]):
            return await self._handle_move("backward", speed, duration)
        if any(w in text for w in ["停止", "ストップ", "とまれ", "止まれ", "stop"]):
            await self._tools.move_robot("stop", speed, 0)
            return "停止しました。"
        if ("右" in text or "左" in text) and any(w in text for w in ["向", "旋回", "回転"]):
            return await self._handle_rotate(text, speed)
        if "三角形" in text:
            return await self._handle_sequence("triangle", speed)
        if "四角形" in text or "正方形" in text:
            return await self._handle_sequence("square", speed)
        if any(w in text for w in ["状態", "今何", "動いてる"]):
            result = self._tools.query_status()
            return f"移動中です（linear_x={result['linear_x']:.2f} m/s）" if result["is_active"] else "停止中です。"
        if any(w in text for w in ["見える", "カメラ", "観察", "確認"]):
            result = await self._tools.observe(text)
            if result["status"] == "ok":
                return f"カメラ画像を取得しました。{result.get('note', '')}（simulate モードではダミー画像です）"
            return f"カメラエラー: {result.get('reason', '不明')}"
        if "登録" in text and ("動き" in text or "マクロ" in text):
            return await self._handle_macro_register(text)
        if "一覧" in text or "マクロ" in text:
            result = await self._tools.manage_macro("list")
            names = result["macros"]
            return f"登録済みマクロ: {', '.join(names)}" if names else "登録済みマクロはありません。"

        return "申し訳ありませんが、その指示には対応していません。「ヘルプ」で使い方を確認できます。"

    # ------------------------------------------------------------------ main loop

    async def _handle_input(self, user_input: str, session_store) -> str:
        if self._use_adk and self._agent and self._session_service:
            return await asyncio.wait_for(
                self._run_with_adk(user_input),
                timeout=self._config["llm"].get("timeout_sec", 5),
            )
        return await self._run_simulate(user_input)

    def _print_startup(self) -> None:
        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")
        mode_label = {"real": "実機", "simulate": "シミュレーション", "dry_run": "ドライラン"}.get(mode, mode)
        model_name = self._config.get("llm", {}).get("model", "不明") if self._use_adk else "—"
        logger.info("\n" + self._WELCOME_MSG)
        logger.info(f"モード: {mode_label} | LLM: {'ADK (' + model_name + ')' if self._use_adk else 'ルールベース（ADK なし）'}")

    def _shutdown(self) -> None:
        state = get_state()
        logger.info("終了します...")
        state.shutdown_event.set()
        state.stop_event.set()
        self._robot.stop()
        if self._ros_node is not None:
            self._ros_node.destroy_node()
            import rclpy  # noqa: PLC0415
            if rclpy.ok():
                rclpy.shutdown()

    async def run(self) -> None:
        self._setup_robot()
        self._setup_tools()
        await self._setup_adk()
        self._print_startup()

        session_store = SessionStore()
        state = get_state()
        try:
            while True:
                try:
                    user_input = input("あなた: ").strip()
                except EOFError:
                    break
                if not user_input:
                    continue
                if self._is_help(user_input):
                    logger.info("\n" + self._WELCOME_MSG)
                    continue
                if self._is_emergency(user_input):
                    state.stop_event.set()
                    self._robot.stop()
                    logger.warning("緊急停止しました。")
                    session_store.save_turn("user", user_input)
                    session_store.save_turn("assistant", "停止しました。")
                    continue

                logger.info(f"入力: {user_input!r}")
                logger.info("考え中...")
                session_store.save_turn("user", user_input)

                try:
                    response = await self._handle_input(user_input, session_store)
                except asyncio.TimeoutError:
                    response = "タイムアウトしました。もう一度お試しください。"
                    logger.error(response)
                except Exception as e:
                    response = f"エラーが発生しました: {e}"
                    logger.error(response)

                session_store.save_turn("assistant", response)
                logger.info(f"応答: {response}")

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
    node.declare_parameter("env_file", "")
    node.declare_parameter("debug", "false")
    node.declare_parameter("debug_dir", "debug")
    raw_debug = node.get_parameter("debug").value
    params = {
        "config_path": node.get_parameter("config_path").value or None,
        "robot_mode": node.get_parameter("robot_mode").value or None,
        "env_file": node.get_parameter("env_file").value or None,
        "debug": raw_debug if isinstance(raw_debug, bool) else str(raw_debug).lower() == "true",
        "debug_dir": node.get_parameter("debug_dir").value or "debug",
    }
    node.destroy_node()
    rclpy.shutdown()
    return params


def _build_config(config_path: str, robot_mode: str | None) -> dict:
    config = RobotController._load_config(config_path)
    if robot_mode:
        config.setdefault("robot", {})["mode"] = robot_mode
    return config


def main_entry() -> None:
    """ROS2 console_scripts エントリポイント。"""
    p = _read_ros2_params()
    _load_dotenv(p.get("env_file"))
    _setup_logging(p.get("debug", False), p.get("debug_dir", "debug"))
    config = _build_config(p.get("config_path") or "config.yaml", p.get("robot_mode"))
    asyncio.run(RobotController(config).run())


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
    asyncio.run(RobotController(config).run())


if __name__ == "__main__":
    cli()
