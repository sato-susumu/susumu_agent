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

import susumu_agent.tools as tools_module
from susumu_agent.camera import CameraClient
from susumu_agent.capabilities import EMERGENCY_KEYWORDS
from susumu_agent.robot.mock_robot import MockRobot
from susumu_agent.session_store import save_turn
from susumu_agent.shared_state import get_state
from susumu_agent.watchdog import Watchdog

# google-adk が未インストールの場合のフォールバック
ADK_AVAILABLE = False
try:
    from google.adk.agents import LlmAgent  # noqa: F401
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    ADK_AVAILABLE = True
except ImportError:
    pass


WELCOME_MSG = """
╔══════════════════════════════════════════════════╗
║       ロボット制御システム 起動しました            ║
╠══════════════════════════════════════════════════╣
║ できること:                                       ║
║   前進・後退・停止・旋回・シーケンス・カメラ確認    ║
║ 例:                                              ║
║   「ゆっくり前進」「右向いて」「三角形を描いて」    ║
║   「何が見える？」「パトロールを登録して」          ║
║ 緊急停止: 「ストップ」と入力                       ║
║ 終了: Ctrl+C または「quit」                       ║
╚══════════════════════════════════════════════════╝
"""


def load_config(path: str = "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def is_emergency(text: str) -> bool:
    normalized = text.strip().lower()
    return any(kw.lower() in normalized for kw in EMERGENCY_KEYWORDS)


def is_help(text: str) -> bool:
    return text.strip() in {"ヘルプ", "help", "何ができる", "使い方", "?", "？"}


def log_status(text: str, state_label: str = "info") -> None:
    colors = {
        "info":      "\033[0m",
        "thinking":  "\033[33m",
        "moving":    "\033[32m",
        "stop":      "\033[31;1m",
        "error":     "\033[31m",
        "ok":        "\033[32m",
    }
    reset = "\033[0m"
    color = colors.get(state_label, "")
    msg = f"{color}{text}{reset}"
    if state_label == "error":
        logger.error(text)
    elif state_label == "stop":
        logger.warning(text)
    else:
        logger.info(text)
    # ターミナル向けカラー出力（loguru の stdout sink を通さず直接出力）
    print(msg)


async def run_with_adk(agent, user_input: str, session_service, session_id: str) -> str:
    """ADK Runner でコマンドを実行する。"""
    runner = Runner(agent=agent, session_service=session_service, app_name="robot_nl")
    from google.genai.types import Content, Part
    content = Content(role="user", parts=[Part(text=user_input)])
    result_text = ""
    async for event in runner.run_async(
        user_id="operator",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    result_text += part.text
    return result_text


async def run_simulate(user_input: str, config: dict) -> str:
    """ADK なしでシミュレーション実行する（開発・動作確認用）。"""
    import re

    text = user_input.strip()

    if is_emergency(text):
        get_state().stop_event.set()
        tools_module._robot.stop()
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
        duration = float(dist_m.group(1)) / tools_module._SPEED_MAP_REF[speed]
    elif dist_cm:
        duration = float(dist_cm.group(1)) / 100 / tools_module._SPEED_MAP_REF[speed]

    if any(w in text for w in ["前進", "前に", "前へ", "まえ", "go", "forward"]):
        result = await tools_module.move_robot("forward", speed, duration)
        return f"前進しました（{result['linear_x']} m/s、{result['duration_sec']} 秒）"

    if any(w in text for w in ["後退", "バック", "うしろ", "後ろ", "backward", "back"]):
        result = await tools_module.move_robot("backward", speed, duration)
        return f"後退しました（{result['linear_x']} m/s、{result['duration_sec']} 秒）"

    if any(w in text for w in ["停止", "ストップ", "とまれ", "止まれ", "stop"]):
        result = await tools_module.move_robot("stop", speed, 0)
        return "停止しました。"

    if "右" in text and ("向" in text or "旋回" in text or "回転" in text):
        angle_m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
        angle = -float(angle_m.group(1)) if angle_m else -90.0
        result = await tools_module.rotate_robot(angle, speed)
        return f"右に{abs(angle):.0f}度旋回しました（{result['duration_sec']} 秒）"

    if "左" in text and ("向" in text or "旋回" in text or "回転" in text):
        angle_m = re.search(r"(\d+(?:\.\d+)?)\s*度", text)
        angle = float(angle_m.group(1)) if angle_m else 90.0
        result = await tools_module.rotate_robot(angle, speed)
        return f"左に{angle:.0f}度旋回しました（{result['duration_sec']} 秒）"

    if "三角形" in text:
        steps = []
        for _ in range(3):
            steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
            steps.append({"type": "rotate", "angle_deg": -120, "speed": speed})
        result = await tools_module.execute_sequence(steps)
        return f"三角形を描きました（{result['completed_steps']}/{result['total']} ステップ完了）"

    if "四角形" in text or "正方形" in text:
        steps = []
        for _ in range(4):
            steps.append({"type": "move", "direction": "forward", "speed": speed, "duration_sec": 2.0})
            steps.append({"type": "rotate", "angle_deg": -90, "speed": speed})
        result = await tools_module.execute_sequence(steps)
        return f"四角形を描きました（{result['completed_steps']}/{result['total']} ステップ完了）"

    if any(w in text for w in ["状態", "今何", "動いてる"]):
        result = tools_module.query_status()
        if result["is_active"]:
            return f"移動中です（linear_x={result['linear_x']:.2f} m/s）"
        return "停止中です。"

    if any(w in text for w in ["見える", "カメラ", "観察", "確認"]):
        result = await tools_module.observe(text)
        if result["status"] == "ok":
            return f"カメラ画像を取得しました。{result.get('note', '')}（simulate モードではダミー画像です）"
        return f"カメラエラー: {result.get('reason', '不明')}"

    if "登録" in text and ("動き" in text or "マクロ" in text):
        last = tools_module.query_last_command()
        if last["status"] == "none":
            return "登録できるコマンドがありません。先に何か動かしてください。"
        name_m = re.search(r"[「『](.+?)[」』]", text)
        name = name_m.group(1) if name_m else "マクロ1"
        result = await tools_module.manage_macro("register", name, [last["last_command"]])
        return result["message"]

    if "一覧" in text or "マクロ" in text:
        result = await tools_module.manage_macro("list")
        names = result["macros"]
        return f"登録済みマクロ: {', '.join(names)}" if names else "登録済みマクロはありません。"

    return "申し訳ありませんが、その指示には対応していません。「ヘルプ」で使い方を確認できます。"


# simulate モード用の速度参照
tools_module._SPEED_MAP_REF = {
    "low": 0.1, "medium": 0.3, "high": 0.5
}


async def main() -> None:
    args = sys.argv[1:]
    config_path = next((a for a in args if not a.startswith("--")), "config.yaml")
    config = load_config(config_path)

    for arg in args:
        if arg.startswith("--robot-mode="):
            config.setdefault("robot", {})["mode"] = arg.split("=", 1)[1]

    robot_cfg = config.get("robot", {})
    mode = robot_cfg.get("mode", "simulate")
    dry_run = (mode == "dry_run")

    ros_node = None
    if mode == "real":
        from susumu_agent.robot.ros2_robot import ROS2_AVAILABLE
        if ROS2_AVAILABLE:
            import rclpy

            from susumu_agent.robot.ros2_robot import ROS2Robot
            if not rclpy.ok():
                rclpy.init()
            ros_node = rclpy.create_node("susumu_agent_robot")
            robot = ROS2Robot(ros_node, robot_cfg.get("cmd_vel_topic", "/cmd_vel"))
        else:
            logger.warning("ROS2 が利用できません。simulate モードに切り替えます。")
            mode = "simulate"
            robot = MockRobot(dry_run=dry_run)
    else:
        robot = MockRobot(dry_run=dry_run)
    tools_module.set_robot(robot)

    camera = CameraClient(
        image_topic=robot_cfg.get("image_topic", "/camera/image_raw"),
        mode=mode,
    )
    tools_module.set_camera(camera)

    watchdog = Watchdog(timeout_sec=robot_cfg.get("watchdog_timeout_sec", 5.0))
    watchdog.start()

    agent = None
    session_service = None
    session_id = "session_001"
    use_adk = ADK_AVAILABLE

    if use_adk:
        try:
            from susumu_agent.agent import create_agent
            agent = create_agent(config)
            session_service = InMemorySessionService()
            await session_service.create_session(
                app_name="robot_nl", user_id="operator", session_id=session_id
            )
            logger.info(f"ADK エージェント起動（モデル: {config['llm']['model']}）")
        except Exception as e:
            logger.error(f"ADK 初期化失敗: {e}\nシミュレーションモードで起動します。")
            use_adk = False

    mode_label = {"real": "実機", "simulate": "シミュレーション", "dry_run": "ドライラン"}.get(mode, mode)
    model_name = config.get("llm", {}).get("model", "不明") if use_adk else "—"
    print(WELCOME_MSG)
    logger.info(f"モード: {mode_label} | LLM: {'ADK (' + model_name + ')' if use_adk else 'ルールベース（ADK なし）'}")
    print()

    state = get_state()
    try:
        while True:
            try:
                user_input = input("あなた: ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            if user_input.lower() in {"quit", "exit", "終了", "q"}:
                break

            if is_help(user_input):
                print(WELCOME_MSG)
                continue

            if is_emergency(user_input):
                state.stop_event.set()
                robot.stop()
                logger.warning("緊急停止しました。")
                save_turn("user", user_input)
                save_turn("assistant", "停止しました。")
                print("\033[31;1m  [停止!] 緊急停止しました。\033[0m")
                print("\033[32m\n停止しました。\n\033[0m")
                continue

            logger.info(f"入力: {user_input!r}")
            print("\033[33m  [考え中...]\033[0m")
            save_turn("user", user_input)

            try:
                if use_adk and agent and session_service:
                    response = await asyncio.wait_for(
                        run_with_adk(agent, user_input, session_service, session_id),
                        timeout=config["llm"].get("timeout_sec", 5),
                    )
                else:
                    response = await run_simulate(user_input, config)
            except asyncio.TimeoutError:
                response = "タイムアウトしました。もう一度お試しください。"
                logger.error(response)
            except Exception as e:
                response = f"エラーが発生しました: {e}"
                logger.error(response)

            save_turn("assistant", response)
            logger.info(f"応答: {response}")
            print(f"\033[32m\n{response}\n\033[0m")

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("終了します...")
        state.shutdown_event.set()
        state.stop_event.set()
        robot.stop()
        if ros_node is not None:
            ros_node.destroy_node()
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
        from susumu_agent.session_store import set_debug_dir
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = str(Path(debug_dir) / f"{ts}_susumu_agent.log")
        setup_loguru(log_path)
        set_debug_dir(debug_dir)
    else:
        # デフォルト: stdout のみ
        logger.remove()
        logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")

    new_argv = [sys.argv[0]]
    if config_path:
        new_argv.append(config_path)
    if robot_mode:
        new_argv.append(f"--robot-mode={robot_mode}")
    sys.argv = new_argv
    asyncio.run(main())


if __name__ == "__main__":
    if _DOTENV_AVAILABLE:
        load_dotenv(override=False)
    logger.remove()
    logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")
    asyncio.run(main())
