"""自然言語ロボット制御システム エントリポイント。

simulate / dry_run モードでは ROS2 不要で動作確認できる。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from loguru import logger

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
    ADK_AVAILABLE = True
except ImportError:
    pass


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
        from susumu_agent.capabilities import EMERGENCY_KEYWORDS
        normalized = text.strip().lower()
        return any(kw.lower() in normalized for kw in EMERGENCY_KEYWORDS)

    def _is_help(self, text: str) -> bool:
        return text.strip() in {"ヘルプ", "help", "何ができる", "使い方", "?", "？"}

    def _setup_robot(self) -> None:
        from susumu_agent.robot.mock_robot import MockRobot
        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")
        dry_run = (mode == "dry_run")

        if mode == "real":
            from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE
            if ROS2_AVAILABLE:
                import rclpy

                from susumu_agent.robot.ros2_robot import ROS2Robot
                if not rclpy.ok():
                    rclpy.init()
                self._ros_node = rclpy.create_node("susumu_agent_robot")
                self._robot = ROS2Robot(self._ros_node, robot_cfg.get("cmd_vel_topic", "/cmd_vel"))
                return
            logger.warning("ROS2 が利用できません。simulate モードに切り替えます。")
            self._config["robot"]["mode"] = "simulate"
        self._robot = MockRobot(dry_run=dry_run)

    def _setup_tools(self) -> None:
        from susumu_agent.camera import CameraClient
        from susumu_agent.macro_store import MacroStore
        from susumu_agent.session_store import SessionStore
        from susumu_agent.tools import RobotTools
        from susumu_agent.watchdog import Watchdog

        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")

        camera = CameraClient(
            image_topic=robot_cfg.get("image_topic", "/camera/image_raw"),
            mode=mode,
        )
        self._tools = RobotTools(
            robot=self._robot,
            camera=camera,
            session_store=SessionStore(),
            macro_store=MacroStore(),
        )

        watchdog = Watchdog(timeout_sec=robot_cfg.get("watchdog_timeout_sec", 5.0))
        watchdog.start()

    async def _setup_adk(self) -> None:
        if not ADK_AVAILABLE:
            return
        try:
            from susumu_agent.agent import AgentFactory
            factory = AgentFactory(self._config)
            self._agent = factory.create_agent(self._tools.get_all_tools())
            self._session_service = InMemorySessionService()
            await self._session_service.create_session(
                app_name="robot_nl", user_id="operator", session_id=self._session_id
            )
            self._use_adk = True
            logger.info(f"ADK エージェント起動（モデル: {self._config['llm']['model']}）")
        except Exception as e:
            logger.error(f"ADK 初期化失敗: {e}\nシミュレーションモードで起動します。")

    async def _run_with_adk(self, user_input: str) -> str:
        runner = Runner(agent=self._agent, session_service=self._session_service, app_name="robot_nl")
        from google.genai.types import Content, Part
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

    async def _run_simulate(self, user_input: str) -> str:
        import re
        text = user_input.strip()

        if self._is_emergency(text):
            from susumu_agent.shared_state import get_state
            get_state().stop_event.set()
            self._robot.stop()
            return "停止しました。"

        speed = "medium"
        if any(w in text for w in ["ゆっくり", "ゆったり", "そろそろ", "ちょっとずつ"]):
            speed = "low"
        elif any(w in text for w in ["素早く", "速く", "全力", "ダッシュ"]):
            speed = "high"

        duration = 2.0
        m = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
        if m:
            duration = float(m.group(1))
        dist_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:メートル|m)\b", text)
        dist_cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:センチ|cm)\b", text)
        if dist_m:
            duration = float(dist_m.group(1)) / self._SPEED_MAP_REF[speed]
        elif dist_cm:
            duration = float(dist_cm.group(1)) / 100 / self._SPEED_MAP_REF[speed]

        if any(w in text for w in ["前進", "前に", "前へ", "まえ", "go", "forward"]):
            result = await self._tools.move_robot("forward", speed, duration)
            return f"前進しました（{result['linear_x']} m/s、{result['duration_sec']} 秒）"
        if any(w in text for w in ["後退", "バック", "うしろ", "後ろ", "backward", "back"]):
            result = await self._tools.move_robot("backward", speed, duration)
            return f"後退しました（{result['linear_x']} m/s、{result['duration_sec']} 秒）"
        if any(w in text for w in ["停止", "ストップ", "とまれ", "止まれ", "stop"]):
            await self._tools.move_robot("stop", speed, 0)
            return "停止しました。"
        if "右" in text and ("向" in text or "旋回" in text or "回転" in text):
            angle_m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
            angle = -float(angle_m.group(1)) if angle_m else -90.0
            result = await self._tools.rotate_robot(angle, speed)
            return f"右に{abs(angle):.0f}度旋回しました（{result['duration_sec']} 秒）"
        if "左" in text and ("向" in text or "旋回" in text or "回転" in text):
            angle_m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
            angle = float(angle_m.group(1)) if angle_m else 90.0
            result = await self._tools.rotate_robot(angle, speed)
            return f"左に{angle:.0f}度旋回しました（{result['duration_sec']} 秒）"
        if "三角形" in text:
            steps = []
            for _ in range(3):
                steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
                steps.append({"type": "rotate", "angle_deg": -120, "speed": speed})
            result = await self._tools.execute_sequence(steps)
            return f"三角形を描きました（{result['completed_steps']}/{result['total']} ステップ完了）"
        if "四角形" in text or "正方形" in text:
            steps = []
            for _ in range(4):
                steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
                steps.append({"type": "rotate", "angle_deg": -90, "speed": speed})
            result = await self._tools.execute_sequence(steps)
            return f"四角形を描きました（{result['completed_steps']}/{result['total']} ステップ完了）"
        if any(w in text for w in ["状態", "今何", "動いてる"]):
            result = self._tools.query_status()
            if result["is_active"]:
                return f"移動中です（linear_x={result['linear_x']:.2f} m/s）"
            return "停止中です。"
        if any(w in text for w in ["見える", "カメラ", "観察", "確認"]):
            result = await self._tools.observe(text)
            if result["status"] == "ok":
                return f"カメラ画像を取得しました。{result.get('note', '')}（simulate モードではダミー画像です）"
            return f"カメラエラー: {result.get('reason', '不明')}"
        if "登録" in text and ("動き" in text or "マクロ" in text):
            last = self._tools.query_last_command()
            if last["status"] == "none":
                return "登録できるコマンドがありません。先に何か動かしてください。"
            name_m = re.search(r"[「『](.+?)[」』]", text)
            name = name_m.group(1) if name_m else "マクロ1"
            result = await self._tools.manage_macro("register", name, [last["last_command"]])
            return result["message"]
        if "一覧" in text or "マクロ" in text:
            result = await self._tools.manage_macro("list")
            names = result["macros"]
            return f"登録済みマクロ: {', '.join(names)}" if names else "登録済みマクロはありません。"

        return "申し訳ありませんが、その指示には対応していません。「ヘルプ」で使い方を確認できます。"

    async def run(self) -> None:
        from susumu_agent.session_store import SessionStore
        from susumu_agent.shared_state import get_state

        self._setup_robot()
        self._setup_tools()
        await self._setup_adk()

        robot_cfg = self._config.get("robot", {})
        mode = robot_cfg.get("mode", "simulate")
        mode_label = {"real": "実機", "simulate": "シミュレーション", "dry_run": "ドライラン"}.get(mode, mode)
        model_name = self._config.get("llm", {}).get("model", "不明") if self._use_adk else "—"
        print(self._WELCOME_MSG)
        logger.info(f"モード: {mode_label} | LLM: {'ADK (' + model_name + ')' if self._use_adk else 'ルールベース（ADK なし）'}")
        print()

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
                    print(self._WELCOME_MSG)
                    continue
                if self._is_emergency(user_input):
                    state.stop_event.set()
                    self._robot.stop()
                    logger.warning("緊急停止しました。")
                    session_store.save_turn("user", user_input)
                    session_store.save_turn("assistant", "停止しました。")
                    print("\033[31;1m  [停止!] 緊急停止しました。\033[0m")
                    print("\033[32m\n停止しました。\n\033[0m")
                    continue

                logger.info(f"入力: {user_input!r}")
                print("\033[33m  [考え中...]\033[0m")
                session_store.save_turn("user", user_input)

                try:
                    if self._use_adk and self._agent and self._session_service:
                        response = await asyncio.wait_for(
                            self._run_with_adk(user_input),
                            timeout=self._config["llm"].get("timeout_sec", 5),
                        )
                    else:
                        response = await self._run_simulate(user_input)
                except asyncio.TimeoutError:
                    response = "タイムアウトしました。もう一度お試しください。"
                    logger.error(response)
                except Exception as e:
                    response = f"エラーが発生しました: {e}"
                    logger.error(response)

                session_store.save_turn("assistant", response)
                logger.info(f"応答: {response}")
                print(f"\033[32m\n{response}\n\033[0m")

        except KeyboardInterrupt:
            pass
        finally:
            logger.info("終了します...")
            state.shutdown_event.set()
            state.stop_event.set()
            self._robot.stop()
            if self._ros_node is not None:
                self._ros_node.destroy_node()
                import rclpy
                if rclpy.ok():
                    rclpy.shutdown()


def main_entry():
    """ROS2 console_scripts エントリポイント。"""
    try:
        import rclpy
        rclpy.init()
        node = rclpy.create_node("susumu_agent_node")
        node.declare_parameter("config_path", "")
        node.declare_parameter("robot_mode", "")
        node.declare_parameter("env_file", "")
        node.declare_parameter("debug", "false")
        node.declare_parameter("debug_dir", "debug")
        config_path = node.get_parameter("config_path").value or None
        robot_mode = node.get_parameter("robot_mode").value or None
        env_file = node.get_parameter("env_file").value or None
        _debug_raw = node.get_parameter("debug").value
        debug = _debug_raw if isinstance(_debug_raw, bool) else str(_debug_raw).lower() == "true"
        debug_dir = node.get_parameter("debug_dir").value or "debug"
        node.destroy_node()
        rclpy.shutdown()
    except Exception:
        config_path = None
        robot_mode = None
        env_file = None
        debug = False
        debug_dir = "debug"

    if _DOTENV_AVAILABLE and env_file:
        load_dotenv(env_file, override=True)
    elif _DOTENV_AVAILABLE:
        load_dotenv(override=False)

    if debug:
        import datetime

        from susumu_agent.ros_logger import setup_loguru
        from susumu_agent.session_store import SessionStore
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = str(Path(debug_dir) / f"{ts}_susumu_agent.log")
        setup_loguru(log_path)
        SessionStore().set_debug_dir(debug_dir)
    else:
        logger.remove()
        logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")

    new_argv = [sys.argv[0]]
    if config_path:
        new_argv.append(config_path)
    if robot_mode:
        new_argv.append(f"--robot-mode={robot_mode}")
    sys.argv = new_argv

    args = sys.argv[1:]
    path = next((a for a in args if not a.startswith("--")), "config.yaml")
    config = RobotController._load_config(path)
    for arg in args:
        if arg.startswith("--robot-mode="):
            config.setdefault("robot", {})["mode"] = arg.split("=", 1)[1]
    asyncio.run(RobotController(config).run())


if __name__ == "__main__":
    if _DOTENV_AVAILABLE:
        load_dotenv(override=False)
    logger.remove()
    logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")
    args = sys.argv[1:]
    path = next((a for a in args if not a.startswith("--")), "config.yaml")
    config = RobotController._load_config(path)
    for arg in args:
        if arg.startswith("--robot-mode="):
            config.setdefault("robot", {})["mode"] = arg.split("=", 1)[1]
    asyncio.run(RobotController(config).run())
