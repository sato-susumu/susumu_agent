"""turtlesim デモノード。エージェント（LLM）を使って自然言語コマンドを自動実行する。"""
from __future__ import annotations

import asyncio
import base64
import datetime
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import NamedTuple

import rclpy
import yaml
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from loguru import logger
from rclpy.node import Node

from susumu_agent.agent.factory import AgentFactory
from susumu_agent.sensors.camera import CameraClient
from susumu_agent.storage.macro_store import MacroStore
from susumu_agent.robot.ros2_robot import ROS2Robot
from susumu_agent.logging.ros_logger import setup_loguru
from susumu_agent.storage.session_store import SessionStore
from susumu_agent.business.shared_state import get_state
from susumu_agent.agent.tools import RobotTools
from susumu_agent.demo.recorder import TurtlesimRecorder
from susumu_agent.business.watchdog import Watchdog

try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    _DOTENV_AVAILABLE = False


class DemoCommand(NamedTuple):
    ja: str
    en: str
    interrupt_after_sec: float = 0.0  # >0 のとき、このコマンド発行後に指定秒数待って緊急停止を割り込ませる


# ------------------------------------------------------------------ SRT helpers

def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(entries: list[dict], path: Path) -> None:
    lines = []
    for i, e in enumerate(entries, 1):
        subtitle_lines = [e["command"], e["command_en"]]
        if e.get("tool_calls"):
            subtitle_lines.extend(e["tool_calls"])
        lines += [
            str(i),
            f"{_srt_time(e['start_sec'])} --> {_srt_time(e['end_sec'])}",
            *subtitle_lines,
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ ffmpeg helpers

def _burn_subtitles(video_path: str, srt_path: str, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", (
            f"subtitles={srt_path}:force_style='"
            "FontSize=14,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=3,Outline=1,Alignment=2'"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-an", output_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(f"字幕焼き込み失敗: {exc.stderr.decode(errors='replace')[:300]}")
        return False


def _make_gif(video_path: str, gif_path: str) -> bool:
    palette = gif_path.replace(".gif", "_palette.png")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "fps=8,scale=480:-1:flags=lanczos,palettegen=max_colors=128",
            palette,
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-i", palette,
            "-filter_complex", "fps=8,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
            gif_path,
        ], check=True, capture_output=True)
        Path(palette).unlink(missing_ok=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error(f"GIF 変換失敗: {exc.stderr.decode(errors='replace')[:300]}")
        return False


# ------------------------------------------------------------------ debug artifact helpers

def _save_labels(label_entries: list[dict], debug_dir: str, ts_str: str) -> None:
    label_path = Path(debug_dir) / f"{ts_str}_demo_labels.jsonl"
    label_path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in label_entries) + "\n",
        encoding="utf-8",
    )
    logger.info(f"ラベル保存: {label_path}")


def _save_camera_image(image_base64: str, step: int, debug_dir: str, ts_str: str) -> None:
    img_path = Path(debug_dir) / f"{ts_str}_observe_step{step:02d}.jpg"
    img_path.write_bytes(base64.b64decode(image_base64))
    logger.info(f"カメラ画像保存: {img_path}")


def _save_video_artifacts(
    video_path: str, srt_entries: list[dict], debug_dir: str, ts_str: str
) -> None:
    srt_path = Path(debug_dir) / f"{ts_str}_turtlesim.srt"
    _write_srt(srt_entries, srt_path)
    logger.info(f"字幕ファイル保存: {srt_path}")

    sub_video = str(Path(debug_dir) / f"{ts_str}_turtlesim.mp4")
    gif_path = str(Path(debug_dir) / f"{ts_str}_turtlesim.gif")
    source = sub_video if _burn_subtitles(video_path, str(srt_path), sub_video) else video_path
    if source == sub_video:
        logger.info(f"字幕付き動画保存: {sub_video}")
    if _make_gif(source, gif_path):
        size_kb = Path(gif_path).stat().st_size // 1024
        suffix = "" if source == sub_video else "（字幕なし）"
        logger.info(f"GIF 保存{suffix}: {gif_path} ({size_kb} KB)")


def _save_debug_artifacts(
    label_entries: list[dict],
    srt_entries: list[dict],
    video_path: str | None,
    record_start_time: float | None,
    debug_dir: str,
) -> None:
    ts_str = datetime.datetime.fromtimestamp(
        record_start_time or datetime.datetime.now().timestamp()
    ).strftime("%Y%m%d_%H%M%S")
    if label_entries:
        _save_labels(label_entries, debug_dir, ts_str)
    if video_path and srt_entries and record_start_time:
        _save_video_artifacts(video_path, srt_entries, debug_dir, ts_str)


# ------------------------------------------------------------------ recorder setup

def _start_recorder(debug: bool, debug_dir: str) -> tuple:
    """録画を開始し (recorder, video_path, start_time) を返す。失敗時は (None, None, None)。"""
    if not debug:
        return None, None, None
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = str(Path(debug_dir) / f"{ts}_turtlesim_raw.mp4")
    recorder = TurtlesimRecorder(video_path)
    recorder.start()
    start_time = datetime.datetime.now().timestamp()
    logger.info(f"録画開始: {video_path}")
    return recorder, video_path, start_time


# ------------------------------------------------------------------ ADK setup

def _build_tools(config: dict, node: Node):
    robot = ROS2Robot(node, "/turtle1/cmd_vel")
    tools = RobotTools(
        robot=robot,
        camera=CameraClient(image_topic="/camera/image_raw", mode="real", node=node),
        session_store=SessionStore(),
        macro_store=MacroStore(),
    )
    Watchdog(timeout_sec=config.get("robot", {}).get("watchdog_timeout_sec", 5.0)).start()
    return tools


async def _setup_adk(config: dict, tools) -> tuple:
    agent = AgentFactory(config).create_agent(tools.get_all_tools(), tools_instance=tools)
    session_service = InMemorySessionService()
    session_id = "demo_session"
    await session_service.create_session(app_name="robot_nl", user_id="demo", session_id=session_id)
    runner = Runner(agent=agent, session_service=session_service, app_name="robot_nl")
    return runner, session_id


# ------------------------------------------------------------------ per-command execution

async def _run_command(runner: Runner, session_id: str, cmd: str) -> str:
    content = Content(role="user", parts=[Part(text=cmd)])
    result_text = ""
    async for event in runner.run_async(user_id="demo", session_id=session_id, new_message=content):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    result_text += part.text
    return result_text.strip()


async def _run_command_with_interrupt(
    runner: Runner,
    session_id: str,
    demo_cmd: DemoCommand,
    tools,
    state,
) -> str:
    """コマンドを実行し、interrupt_after_sec > 0 なら指定秒後に緊急停止を割り込ませる。"""
    if demo_cmd.interrupt_after_sec <= 0:
        return await _run_command(runner, session_id, demo_cmd.ja)

    async def _interrupt() -> None:
        await asyncio.sleep(demo_cmd.interrupt_after_sec)
        logger.info(f"割り込み停止（{demo_cmd.interrupt_after_sec}秒後）")
        state.stop_event.set()
        await tools._robot.stop()

    cmd_task = asyncio.create_task(_run_command(runner, session_id, demo_cmd.ja))
    interrupt_task = asyncio.create_task(_interrupt())
    try:
        response = await cmd_task
    finally:
        interrupt_task.cancel()
    return response


# ------------------------------------------------------------------ DemoRunner

class DemoRunner:
    _DEMO_COMMANDS: list[DemoCommand] = [
        DemoCommand("素早く3秒前進して",                        "Move forward fast for 3 seconds"),
        DemoCommand("右に90度、素早く回転して",                  "Turn right 90 degrees fast"),
        DemoCommand("素早く3秒前進して",                        "Move forward fast for 3 seconds"),
        DemoCommand("左に90度、素早く回転して",                  "Turn left 90 degrees fast"),
        DemoCommand("三角形を描いて。1辺は素早く3秒で移動すること", "Draw a triangle fast (3 sec per side)"),
        DemoCommand("カメラに何が映っている？",                  "What does the camera see?"),
        # 正方形を描いている途中（5秒後）にストップを割り込ませる
        DemoCommand("正方形を描いて。1辺は素早く3秒で移動すること", "Draw a square fast (3 sec per side)", interrupt_after_sec=5.0),
        DemoCommand("ストップ",                                "Stop"),
    ]

    def __init__(self, config: dict, node: Node, debug: bool = False, debug_dir: str = "debug") -> None:
        self._config = config
        self._node = node
        self._debug = debug
        self._debug_dir = debug_dir

    def _collect_camera_image_if_needed(
        self, demo_cmd: DemoCommand, tools, step: int, ts_str: str
    ) -> None:
        if not self._debug or "カメラ" not in demo_cmd.ja:
            return
        img_result = tools._camera.get_latest_image()
        if img_result.get("status") == "ok" and img_result.get("image_base64"):
            _save_camera_image(img_result["image_base64"], step, self._debug_dir, ts_str)

    def _make_label_entry(
        self, step: int, demo_cmd: DemoCommand, response: str, tool_calls: list[str]
    ) -> dict:
        return {
            "step": step,
            "timestamp": datetime.datetime.now().isoformat(),
            "command": demo_cmd.ja,
            "command_en": demo_cmd.en,
            "response": response,
            "tool_calls": tool_calls,
        }

    def _make_srt_entry(
        self,
        demo_cmd: DemoCommand,
        response: str,
        tool_calls: list[str],
        cmd_start: float,
        cmd_end: float,
        record_start_time: float,
    ) -> dict:
        return {
            "start_sec": cmd_start - record_start_time,
            "end_sec": cmd_end - record_start_time,
            "command": demo_cmd.ja,
            "command_en": demo_cmd.en,
            "response": response,
            "tool_calls": tool_calls,
        }

    async def run(self) -> None:
        tools = _build_tools(self._config, self._node)
        runner, session_id = await _setup_adk(self._config, tools)
        recorder, video_path, record_start_time = _start_recorder(self._debug, self._debug_dir)

        label_entries: list[dict] = []
        srt_entries: list[dict] = []

        state = get_state()
        logger.info("turtlesim エージェントデモ開始")

        total = len(self._DEMO_COMMANDS)
        ts_str = datetime.datetime.fromtimestamp(
            record_start_time or datetime.datetime.now().timestamp()
        ).strftime("%Y%m%d_%H%M%S")

        try:
            for i, demo_cmd in enumerate(self._DEMO_COMMANDS):
                logger.info(f"[{i+1}/{total}] 入力: {demo_cmd.ja!r}")
                state.stop_event.clear()
                tools.clear_tool_call_log()
                cmd_start = datetime.datetime.now().timestamp()

                response = await _run_command_with_interrupt(
                    runner, session_id, demo_cmd, tools, state
                )
                cmd_end = datetime.datetime.now().timestamp()
                tool_calls = tools.get_tool_call_log()
                logger.info(f"応答: {response}")

                self._collect_camera_image_if_needed(demo_cmd, tools, i + 1, ts_str)

                if self._debug:
                    label_entries.append(
                        self._make_label_entry(i + 1, demo_cmd, response, tool_calls)
                    )
                    if record_start_time is not None:
                        srt_entries.append(
                            self._make_srt_entry(
                                demo_cmd, response, tool_calls, cmd_start, cmd_end, record_start_time
                            )
                        )

                await asyncio.sleep(1.0)
        finally:
            if recorder is not None:
                recorder.stop()
                logger.info("録画終了")
            if self._debug:
                _save_debug_artifacts(
                    label_entries, srt_entries, video_path, record_start_time, self._debug_dir
                )

        logger.info("デモ完了")


# ------------------------------------------------------------------ entry point

def _setup_logging(debug: bool, debug_dir: str) -> None:
    if debug:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        setup_loguru(str(Path(debug_dir) / f"{ts}_susumu_agent_demo.log"))
        SessionStore().set_debug_dir(debug_dir)
    else:
        logger.remove()
        logger.add(sys.stderr, format="{time:HH:mm:ss} [{level}] {message}")


def main() -> None:
    rclpy.init()
    node = Node("susumu_agent_demo")
    node.declare_parameter("config_path", "")
    node.declare_parameter("env_file", "")
    node.declare_parameter("debug", "false")
    node.declare_parameter("debug_dir", "debug")
    config_path = node.get_parameter("config_path").value or "config.yaml"
    env_file = node.get_parameter("env_file").value or None
    raw = node.get_parameter("debug").value
    debug = raw if isinstance(raw, bool) else str(raw).lower() == "true"
    debug_dir = node.get_parameter("debug_dir").value or "debug"

    if _DOTENV_AVAILABLE and env_file:
        load_dotenv(env_file, override=True)
    elif _DOTENV_AVAILABLE:
        load_dotenv(override=False)

    _setup_logging(debug, debug_dir)

    p = Path(config_path)
    config = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}

    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    try:
        asyncio.run(DemoRunner(config, node, debug=debug, debug_dir=debug_dir).run())
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
