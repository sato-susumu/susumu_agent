"""自然言語ロボット制御システム エントリポイント。

simulate / dry_run モードでは ROS2 不要で動作確認できる。
"""
from __future__ import annotations
import asyncio
import sys
import yaml
from pathlib import Path

from capabilities import EMERGENCY_KEYWORDS, build_system_prompt
from shared_state import get_state
from watchdog import Watchdog
from camera import CameraClient
from robot.mock_robot import MockRobot
import tools as tools_module
from session_store import save_turn, append_command_log

# google-adk が未インストールの場合のフォールバック
ADK_AVAILABLE = False
try:
    from google.adk.agents import LlmAgent
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


def print_status(text: str, state_label: str = "info") -> None:
    colors = {
        "info":      "\033[0m",
        "thinking":  "\033[33m",   # 黄
        "moving":    "\033[32m",   # 緑
        "stop":      "\033[31;1m", # 赤・太字
        "error":     "\033[31m",   # 赤
        "ok":        "\033[32m",   # 緑
    }
    reset = "\033[0m"
    color = colors.get(state_label, "")
    print(f"{color}{text}{reset}")


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

    # 緊急停止
    if is_emergency(text):
        get_state().stop_event.set()
        tools_module._robot.stop()
        return "停止しました。"

    # 前進系
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

    # 旋回
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

    # シーケンス
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

    # 状態確認
    if any(w in text for w in ["状態", "今何", "動いてる"]):
        result = tools_module.query_status()
        if result["is_active"]:
            return f"移動中です（linear_x={result['linear_x']:.2f} m/s）"
        return "停止中です。"

    # カメラ
    if any(w in text for w in ["見える", "カメラ", "観察", "確認"]):
        result = await tools_module.observe(text)
        if result["status"] == "ok":
            return f"カメラ画像を取得しました。{result.get('note', '')}（simulate モードではダミー画像です）"
        return f"カメラエラー: {result.get('reason', '不明')}"

    # マクロ
    if "登録" in text and ("動き" in text or "マクロ" in text):
        last = tools_module.query_last_command()
        if last["status"] == "none":
            return "登録できるコマンドがありません。先に何か動かしてください。"
        name_m = re.search(r"[「『](.+?)[」』]", text)
        name = name_m.group(1) if name_m else "マクロ1"
        result = await tools_module.manage_macro("register", name,
                                                  [last["last_command"]])
        return result["message"]

    if "一覧" in text or "マクロ" in text:
        result = await tools_module.manage_macro("list")
        names = result["macros"]
        return f"登録済みマクロ: {', '.join(names)}" if names else "登録済みマクロはありません。"

    return "申し訳ありませんが、その指示には対応していません。「ヘルプ」で使い方を確認できます。"


# simulate モード用の速度参照（tools.py の SPEED_MAP を参照）
tools_module._SPEED_MAP_REF = {
    "low": 0.1, "medium": 0.3, "high": 0.5
}


async def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)

    robot_cfg = config.get("robot", {})
    mode = robot_cfg.get("mode", "simulate")
    dry_run = (mode == "dry_run")

    # ロボットバックエンドを設定
    if mode == "real":
        from robot.ros2_robot import ROS2_AVAILABLE
        if not ROS2_AVAILABLE:
            print("ROS2 が利用できません。simulate モードに切り替えます。")
            mode = "simulate"

    robot = MockRobot(dry_run=dry_run)
    tools_module.set_robot(robot)

    camera = CameraClient(
        image_topic=robot_cfg.get("image_topic", "/camera/image_raw"),
        mode=mode,
    )
    tools_module.set_camera(camera)

    # Watchdog 起動
    watchdog = Watchdog(timeout_sec=robot_cfg.get("watchdog_timeout_sec", 5.0))
    watchdog.start()

    # ADK エージェント準備
    agent = None
    session_service = None
    session_id = "session_001"
    # simulate モードでも ADK が使える（MockRobot にツールを向けているため）
    use_adk = ADK_AVAILABLE

    if use_adk:
        try:
            from agent import create_agent
            agent = create_agent(config)
            session_service = InMemorySessionService()
            await session_service.create_session(
                app_name="robot_nl", user_id="operator", session_id=session_id
            )
            print_status(f"ADK エージェント起動（モデル: {config['llm']['model']}）", "ok")
        except Exception as e:
            print_status(f"ADK 初期化失敗: {e}\nシミュレーションモードで起動します。", "error")
            use_adk = False

    mode_label = {"real": "実機", "simulate": "シミュレーション", "dry_run": "ドライラン"}.get(mode, mode)
    model_name = config.get("llm", {}).get("model", "不明") if use_adk else "—"
    print(WELCOME_MSG)
    print_status(f"モード: {mode_label} | LLM: {'ADK (' + model_name + ')' if use_adk else 'ルールベース（ADK なし）'}", "info")
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

            # 緊急停止は最優先でLLMを経由しない
            if is_emergency(user_input):
                state.stop_event.set()
                robot.stop()
                print_status("  [停止!] 緊急停止しました。", "stop")
                save_turn("user", user_input)
                save_turn("assistant", "停止しました。")
                print_status("\n🤖 停止しました。\n", "ok")
                continue

            print_status("  [考え中...]", "thinking")
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
                print_status(f"  [エラー] {response}", "error")
            except Exception as e:
                response = f"エラーが発生しました: {e}"
                print_status(f"  [エラー] {response}", "error")

            save_turn("assistant", response)
            print_status(f"\n🤖 {response}\n", "ok")

    except KeyboardInterrupt:
        pass
    finally:
        print_status("\n終了します...", "info")
        state.shutdown_event.set()
        state.stop_event.set()
        robot.stop()


def main_entry():
    """ROS2 console_scripts エントリポイント。"""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
