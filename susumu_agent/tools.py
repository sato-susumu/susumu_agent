from __future__ import annotations

from typing import Literal

from susumu_agent.capabilities import (
    SPEED_MAP,
    angle_to_duration,
    clamp_angle,
    clamp_duration,
)
from susumu_agent.macro_store import delete_macro, get_macro, list_macros, save_macro
from susumu_agent.session_store import append_command_log
from susumu_agent.shared_state import get_state

# ツール実行時に注入される RobotInterface インスタンス
_robot = None


def set_robot(robot) -> None:
    global _robot
    _robot = robot


# ─────────────────────────────────────────────
# ツール実装
# ─────────────────────────────────────────────

async def move_robot(
    direction: Literal["forward", "backward", "stop"],
    speed: Literal["low", "medium", "high"] = "medium",
    duration_sec: float = 2.0,
) -> dict:
    """ロボットを前進・後退・停止させる。

    Args:
        direction: 移動方向。forward=前進、backward=後退、stop=停止。
        speed: 速度。low=ゆっくり、medium=標準、high=素早く。
        duration_sec: 継続時間（秒）。0.1〜30.0。stop の場合は無視される。
    """
    duration_sec = clamp_duration(duration_sec)
    state = get_state()
    state.last_command = {"tool": "move_robot", "direction": direction,
                           "speed": speed, "duration_sec": duration_sec}

    append_command_log({"event": "tool_call", "tool": "move_robot",
                        "direction": direction, "speed": speed, "duration_sec": duration_sec})

    if state.stop_event.is_set():
        return {"status": "aborted", "reason": "緊急停止中"}

    await _robot.move(direction, speed, duration_sec)
    return {"status": "ok", "direction": direction, "speed": speed,
            "linear_x": SPEED_MAP[speed]["linear"], "duration_sec": duration_sec}


async def rotate_robot(
    angle_deg: float,
    speed: Literal["low", "medium", "high"] = "medium",
) -> dict:
    """ロボットをその場で旋回させる。

    Args:
        angle_deg: 回転角度（度）。正=左回り、負=右回り。範囲: -360〜+360。
        speed: 角速度レベル。low/medium/high。
    """
    angle_deg = clamp_angle(angle_deg)
    duration_sec = angle_to_duration(angle_deg, speed)
    state = get_state()
    state.last_command = {"tool": "rotate_robot", "angle_deg": angle_deg, "speed": speed}

    append_command_log({"event": "tool_call", "tool": "rotate_robot",
                        "angle_deg": angle_deg, "speed": speed})

    if state.stop_event.is_set():
        return {"status": "aborted", "reason": "緊急停止中"}

    await _robot.rotate(angle_deg, speed)
    return {"status": "ok", "angle_deg": angle_deg, "speed": speed,
            "duration_sec": round(duration_sec, 2)}


async def execute_sequence(steps: list[dict]) -> dict:
    """複数の移動ステップを順番に実行する。

    Args:
        steps: 実行するステップのリスト。各ステップは move_robot または rotate_robot
               のパラメータを持つ dict。
               移動ステップ例: {"type": "move", "direction": "forward", "speed": "medium", "duration_sec": 2.0}
               旋回ステップ例: {"type": "rotate", "angle_deg": -90, "speed": "medium"}
    """
    state = get_state()
    total = len(steps)
    completed = 0

    append_command_log({"event": "tool_call", "tool": "execute_sequence", "total_steps": total})

    for i, step in enumerate(steps):
        if state.stop_event.is_set():
            return {"status": "interrupted", "completed_steps": completed, "total": total}

        step_type = step.get("type", "move")
        if step_type == "rotate":
            await rotate_robot(
                angle_deg=step.get("angle_deg", 0),
                speed=step.get("speed", "medium"),
            )
        else:
            await move_robot(
                direction=step.get("direction", "forward"),
                speed=step.get("speed", "medium"),
                duration_sec=step.get("duration_sec", 2.0),
            )
        completed += 1

    return {"status": "ok", "completed_steps": completed, "total": total}


async def observe(
    question: str,
    sensor: Literal["camera"] = "camera",
) -> dict:
    """カメラで前方を撮影し、画像データを返す。Claude が内容を解析する。

    Args:
        question: カメラ画像について尋ねる質問。
        sensor: 使用するセンサー（現在は camera のみ対応）。
    """
    from susumu_agent.camera import CameraClient
    # camera クライアントは tools モジュール初期化時に設定
    camera: CameraClient = _camera
    result = camera.get_latest_image()

    if result["status"] != "ok":
        return result

    return {
        "status": "ok",
        "question": question,
        "image_base64": result["image_base64"],
        "note": result.get("note", ""),
    }


def query_status() -> dict:
    """現在のロボットの移動状態を返す。"""
    return _robot.get_status()


def query_last_command() -> dict:
    """直前に実行したコマンドの内容を返す。"""
    state = get_state()
    if state.last_command is None:
        return {"status": "none", "message": "まだコマンドを実行していません"}
    return {"status": "ok", "last_command": state.last_command}


async def manage_macro(
    action: Literal["register", "run", "delete", "list"],
    name: str = "",
    steps: list[dict] | None = None,
) -> dict:
    """マクロを登録・実行・削除・一覧表示する。

    Args:
        action: register=登録、run=実行、delete=削除、list=一覧。
        name: マクロ名（list 以外で必要）。
        steps: 登録するステップ（register のみ）。
    """
    if action == "list":
        names = list_macros()
        return {"status": "ok", "macros": names}

    if action == "register":
        if not steps:
            return {"status": "error", "reason": "steps が空です"}
        save_macro(name, steps)
        return {"status": "ok", "message": f"マクロ「{name}」を登録しました"}

    if action == "delete":
        ok = delete_macro(name)
        return {"status": "ok" if ok else "error",
                "message": f"マクロ「{name}」を削除しました" if ok else f"マクロ「{name}」が見つかりません"}

    if action == "run":
        stored = get_macro(name)
        if stored is None:
            return {"status": "error", "reason": f"マクロ「{name}」が登録されていません"}
        return await execute_sequence(stored)

    return {"status": "error", "reason": f"不明な action: {action}"}


def report_unsupported(reason: str) -> dict:
    """ユーザーの指示がロボットの能力範囲外の場合に呼び出す。

    Args:
        reason: できない理由の説明（日本語）。
    """
    append_command_log({"event": "unsupported", "reason": reason})
    return {"status": "unsupported", "reason": reason}


# カメラクライアントの注入
_camera = None


def set_camera(camera) -> None:
    global _camera
    _camera = camera


# ADK に渡すツールリスト
ALL_TOOLS = [
    move_robot,
    rotate_robot,
    execute_sequence,
    observe,
    query_status,
    query_last_command,
    manage_macro,
    report_unsupported,
]
