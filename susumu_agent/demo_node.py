"""turtlesim デモノード。エージェント（LLM）を使って自然言語コマンドを自動実行する。"""
from __future__ import annotations

import asyncio
import datetime
import json
import subprocess
import sys
from pathlib import Path

import rclpy
import yaml
from loguru import logger
from rclpy.node import Node

try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False


class DemoRunner:
    _DEMO_COMMANDS = [
        "素早く3秒前進して",
        "右に90度、素早く回転して",
        "素早く3秒前進して",
        "左に90度、素早く回転して",
        "三角形を描いて。1辺は素早く3秒で移動すること",
        "正方形を描いて。1辺は素早く3秒で移動すること",
        "ストップ",
    ]

    _COMMAND_EN = {
        "素早く3秒前進して":                        "Move forward fast for 3 seconds",
        "右に90度、素早く回転して":                  "Turn right 90 degrees fast",
        "左に90度、素早く回転して":                  "Turn left 90 degrees fast",
        "三角形を描いて。1辺は素早く3秒で移動すること": "Draw a triangle fast (3 sec per side)",
        "正方形を描いて。1辺は素早く3秒で移動すること": "Draw a square fast (3 sec per side)",
        "ストップ":                                "Stop",
    }

    def __init__(self, config: dict, node: Node, debug: bool = False, debug_dir: str = "debug") -> None:
        self._config = config
        self._node = node
        self._debug = debug
        self._debug_dir = debug_dir

    @staticmethod
    def _srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _write_srt(self, entries: list[dict], path: Path) -> None:
        lines = []
        for i, e in enumerate(entries, 1):
            lines.append(str(i))
            lines.append(f"{self._srt_time(e['start_sec'])} --> {self._srt_time(e['end_sec'])}")
            lines.append(e["command"])
            lines.append(e["command_en"])
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")

    def _burn_subtitles(self, video_path: str, srt_path: str, output_path: str) -> bool:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"subtitles={srt_path}:force_style='FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=1,Alignment=2'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", output_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as exc:
            logger.error(f"字幕焼き込み失敗: {exc.stderr.decode(errors='replace')[:300]}")
            return False

    def _make_gif(self, video_path: str, gif_path: str) -> bool:
        palette = gif_path.replace(".gif", "_palette.png")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-vf", "fps=8,scale=320:-1:flags=lanczos,palettegen=max_colors=128",
                palette,
            ], check=True, capture_output=True)
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-i", palette,
                "-filter_complex", "fps=8,scale=320:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
                gif_path,
            ], check=True, capture_output=True)
            Path(palette).unlink(missing_ok=True)
            return True
        except subprocess.CalledProcessError as exc:
            logger.error(f"GIF 変換失敗: {exc.stderr.decode(errors='replace')[:300]}")
            return False

    async def run(self) -> None:
        from susumu_agent.camera import CameraClient
        from susumu_agent.macro_store import MacroStore
        from susumu_agent.robot.ros2_robot import ROS2Robot
        from susumu_agent.session_store import SessionStore
        from susumu_agent.shared_state import get_state
        from susumu_agent.tools import RobotTools
        from susumu_agent.watchdog import Watchdog

        robot = ROS2Robot(self._node, "/turtle1/cmd_vel")
        session_store = SessionStore()
        tools = RobotTools(
            robot=robot,
            camera=CameraClient(mode="simulate"),
            session_store=session_store,
            macro_store=MacroStore(),
        )

        watchdog = Watchdog(timeout_sec=self._config.get("robot", {}).get("watchdog_timeout_sec", 5.0))
        watchdog.start()

        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai.types import Content, Part

            from susumu_agent.agent import AgentFactory
        except ImportError as e:
            logger.error(f"ADK が利用できません: {e}")
            return

        factory = AgentFactory(self._config)
        agent = factory.create_agent(tools.get_all_tools())
        session_service = InMemorySessionService()
        session_id = "demo_session"
        await session_service.create_session(app_name="robot_nl", user_id="demo", session_id=session_id)

        logger.info("turtlesim エージェントデモ開始")

        recorder = None
        video_path: str | None = None
        record_start_time: float | None = None
        if self._debug:
            try:
                from susumu_agent.turtlesim_recorder import TurtlesimRecorder
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                video_path = str(Path(self._debug_dir) / f"{ts}_turtlesim_raw.mp4")
                recorder = TurtlesimRecorder(video_path)
                recorder.start()
                record_start_time = datetime.datetime.now().timestamp()
                logger.info(f"録画開始: {video_path}")
            except Exception as e:
                logger.warning(f"録画開始失敗（スキップ）: {e}")

        label_entries: list[dict] = []
        srt_entries: list[dict] = []
        state = get_state()

        try:
            for i, cmd in enumerate(self._DEMO_COMMANDS):
                logger.info(f"[{i+1}/{len(self._DEMO_COMMANDS)}] 入力: {cmd!r}")
                state.stop_event.clear()
                cmd_start_time = datetime.datetime.now().timestamp()

                runner = Runner(agent=agent, session_service=session_service, app_name="robot_nl")
                content = Content(role="user", parts=[Part(text=cmd)])
                result_text = ""
                async for event in runner.run_async(user_id="demo", session_id=session_id, new_message=content):
                    if event.is_final_response() and event.content:
                        for part in event.content.parts:
                            if hasattr(part, "text") and part.text:
                                result_text += part.text

                cmd_end_time = datetime.datetime.now().timestamp()
                response = result_text.strip()
                logger.info(f"応答: {response}")

                if self._debug:
                    label_entries.append({
                        "step": i + 1,
                        "timestamp": datetime.datetime.now().isoformat(),
                        "command": cmd,
                        "command_en": self._COMMAND_EN.get(cmd, cmd),
                        "response": response,
                    })
                    if record_start_time is not None:
                        srt_entries.append({
                            "start_sec": cmd_start_time - record_start_time,
                            "end_sec": cmd_end_time - record_start_time,
                            "command": cmd,
                            "command_en": self._COMMAND_EN.get(cmd, cmd),
                            "response": response,
                        })

                await asyncio.sleep(1.0)
        finally:
            if recorder is not None:
                recorder.stop()
                logger.info("録画終了")

            if self._debug and label_entries:
                ts = datetime.datetime.fromtimestamp(
                    record_start_time or datetime.datetime.now().timestamp()
                ).strftime("%Y%m%d_%H%M%S")
                label_path = Path(self._debug_dir) / f"{ts}_demo_labels.jsonl"
                label_path.write_text(
                    "\n".join(json.dumps(e, ensure_ascii=False) for e in label_entries) + "\n",
                    encoding="utf-8",
                )
                logger.info(f"ラベル保存: {label_path}")

            if self._debug and video_path and srt_entries and record_start_time:
                ts_str = datetime.datetime.fromtimestamp(record_start_time).strftime("%Y%m%d_%H%M%S")
                srt_path = Path(self._debug_dir) / f"{ts_str}_turtlesim.srt"
                self._write_srt(srt_entries, srt_path)
                logger.info(f"字幕ファイル保存: {srt_path}")

                sub_video = str(Path(self._debug_dir) / f"{ts_str}_turtlesim.mp4")
                gif_path = str(Path(self._debug_dir) / f"{ts_str}_turtlesim.gif")
                if self._burn_subtitles(video_path, str(srt_path), sub_video):
                    logger.info(f"字幕付き動画保存: {sub_video}")
                    if self._make_gif(sub_video, gif_path):
                        size_kb = Path(gif_path).stat().st_size // 1024
                        logger.info(f"GIF 保存: {gif_path} ({size_kb} KB)")
                else:
                    if self._make_gif(video_path, gif_path):
                        size_kb = Path(gif_path).stat().st_size // 1024
                        logger.info(f"GIF 保存（字幕なし）: {gif_path} ({size_kb} KB)")

        logger.info("デモ完了")


def main() -> None:
    rclpy.init()
    node = Node("susumu_agent_demo")
    node.declare_parameter("config_path", "")
    node.declare_parameter("env_file", "")
    node.declare_parameter("debug", "false")
    node.declare_parameter("debug_dir", "debug")
    config_path = node.get_parameter("config_path").value or "config.yaml"
    env_file = node.get_parameter("env_file").value or None
    _debug_raw = node.get_parameter("debug").value
    debug = _debug_raw if isinstance(_debug_raw, bool) else str(_debug_raw).lower() == "true"
    debug_dir = node.get_parameter("debug_dir").value or "debug"

    if _DOTENV_AVAILABLE and env_file:
        load_dotenv(env_file, override=True)
    elif _DOTENV_AVAILABLE:
        load_dotenv(override=False)

    if debug:
        from susumu_agent.ros_logger import setup_loguru
        from susumu_agent.session_store import SessionStore
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = str(Path(debug_dir) / f"{ts}_susumu_agent_demo.log")
        setup_loguru(log_path)
        SessionStore().set_debug_dir(debug_dir)
    else:
        logger.remove()
        logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")

    p = Path(config_path)
    config = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}

    try:
        asyncio.run(DemoRunner(config, node, debug=debug, debug_dir=debug_dir).run())
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
