from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Literal

from google.genai import types as genai_types
from loguru import logger

from susumu_agent.business.capabilities import (
    SPEED_MAP,
    angle_to_duration,
    clamp_angle,
    clamp_duration,
)
from susumu_agent.business.shared_state import get_state


class RobotTools:
    def __init__(self, robot, camera, session_store, macro_store) -> None:
        self._robot = robot
        self._camera = camera
        self._session_store = session_store
        self._macro_store = macro_store
        self._tool_call_log: list[str] = []
        self._pending_image_parts: list[genai_types.Part] = []
        self._agent_event_callback: Callable[[dict], None] | None = None

    def set_agent_event_callback(self, callback: Callable[[dict], None]) -> None:
        self._agent_event_callback = callback

    def _emit(self, event: dict) -> None:
        if self._agent_event_callback is not None:
            try:
                self._agent_event_callback(event)
            except Exception as e:
                logger.warning(f"[tool] agent_event_callback エラー: {e}")

    def clear_tool_call_log(self) -> None:
        self._tool_call_log.clear()

    def get_tool_call_log(self) -> list[str]:
        return list(self._tool_call_log)

    def pop_pending_image_parts(self) -> list[genai_types.Part]:
        parts = self._pending_image_parts
        self._pending_image_parts = []
        return parts

    async def move_robot(
        self,
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
        msg = f"move_robot(direction={direction!r}, speed={speed!r}, duration_sec={duration_sec})"
        logger.info(f"[tool] {msg}")
        self._tool_call_log.append(msg)
        state = get_state()
        state.last_command = {"tool": "move_robot", "direction": direction,
                               "speed": speed, "duration_sec": duration_sec}
        self._session_store.append_command_log({"event": "tool_call", "tool": "move_robot",
                                                "direction": direction, "speed": speed,
                                                "duration_sec": duration_sec})
        self._emit({"type": "tool_start", "tool": "move_robot",
                    "direction": direction, "speed": speed, "duration_sec": duration_sec})
        if state.stop_event.is_set():
            self._emit({"type": "tool_done", "tool": "move_robot", "status": "aborted"})
            return {"status": "aborted", "reason": "緊急停止中"}
        await self._robot.move(direction, speed, duration_sec)
        self._emit({"type": "tool_done", "tool": "move_robot", "status": "ok",
                    "direction": direction, "speed": speed, "duration_sec": duration_sec})
        return {"status": "ok", "direction": direction, "speed": speed,
                "linear_x": SPEED_MAP[speed]["linear"], "duration_sec": duration_sec}

    async def rotate_robot(
        self,
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
        msg = f"rotate_robot(angle_deg={angle_deg}, speed={speed!r})"
        logger.info(f"[tool] {msg}")
        self._tool_call_log.append(msg)
        state = get_state()
        state.last_command = {"tool": "rotate_robot", "angle_deg": angle_deg, "speed": speed}
        self._session_store.append_command_log({"event": "tool_call", "tool": "rotate_robot",
                                                "angle_deg": angle_deg, "speed": speed})
        self._emit({"type": "tool_start", "tool": "rotate_robot",
                    "angle_deg": angle_deg, "speed": speed})
        if state.stop_event.is_set():
            self._emit({"type": "tool_done", "tool": "rotate_robot", "status": "aborted"})
            return {"status": "aborted", "reason": "緊急停止中"}
        await self._robot.rotate(angle_deg, speed)
        self._emit({"type": "tool_done", "tool": "rotate_robot", "status": "ok",
                    "angle_deg": angle_deg, "speed": speed, "duration_sec": round(duration_sec, 2)})
        return {"status": "ok", "angle_deg": angle_deg, "speed": speed,
                "duration_sec": round(duration_sec, 2)}

    async def execute_sequence(self, steps: list[dict]) -> dict:
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
        msg = f"execute_sequence(total_steps={total})"
        logger.info(f"[tool] {msg}")
        self._tool_call_log.append(msg)
        self._session_store.append_command_log({"event": "tool_call", "tool": "execute_sequence",
                                                "total_steps": total})
        self._emit({"type": "tool_start", "tool": "execute_sequence", "total_steps": total})
        for step in steps:
            if state.stop_event.is_set():
                logger.info(f"[tool] execute_sequence 中断（{completed}/{total} 完了）")
                self._emit({"type": "tool_done", "tool": "execute_sequence", "status": "interrupted",
                            "completed_steps": completed, "total": total})
                return {"status": "interrupted", "completed_steps": completed, "total": total}
            if step.get("type") == "rotate":
                await self.rotate_robot(
                    angle_deg=step.get("angle_deg", 0),
                    speed=step.get("speed", "medium"),
                )
            else:
                await self.move_robot(
                    direction=step.get("direction", "forward"),
                    speed=step.get("speed", "medium"),
                    duration_sec=step.get("duration_sec", 2.0),
                )
            completed += 1
        self._emit({"type": "tool_done", "tool": "execute_sequence", "status": "ok",
                    "completed_steps": completed, "total": total})
        return {"status": "ok", "completed_steps": completed, "total": total}

    async def observe(
        self,
        question: str,
        sensor: Literal["camera"] = "camera",
    ) -> dict:
        """カメラで前方を撮影し、画像データを返す。LLM が内容を解析する。

        Args:
            question: カメラ画像について尋ねる質問。
            sensor: 使用するセンサー（現在は camera のみ対応）。
        """
        msg = f"observe(question={question!r}, sensor={sensor!r})"
        logger.info(f"[tool] {msg}")
        self._tool_call_log.append(msg)
        result = self._camera.get_latest_image()
        if result["status"] != "ok":
            logger.warning(f"[tool] observe: カメラ取得失敗 status={result['status']}")
            return result
        image_base64 = result["image_base64"]
        logger.info(f"[tool] observe: 画像取得成功（{len(image_base64)} bytes base64）")
        # 画像パートを pending に保持し、before_model_callback で LLM リクエストに追加する
        # （state 経由だと InMemorySessionService の deepcopy で大きなバイナリが毎回コピーされハングする）
        image_bytes = base64.b64decode(image_base64)
        self._pending_image_parts = [
            genai_types.Part(text=f"カメラ画像を取得しました。質問: {question}"),
            genai_types.Part(inline_data=genai_types.Blob(data=image_bytes, mime_type="image/jpeg")),
        ]
        return {"status": "ok", "question": question, "note": result.get("note", "")}

    def query_status(self) -> dict:
        """現在のロボットの移動状態を返す。"""
        logger.info("[tool] query_status()")
        return self._robot.get_status()

    def query_last_command(self) -> dict:
        """直前に実行したコマンドの内容を返す。"""
        logger.info("[tool] query_last_command()")
        state = get_state()
        if state.last_command is None:
            return {"status": "none", "message": "まだコマンドを実行していません"}
        return {"status": "ok", "last_command": state.last_command}

    async def manage_macro(
        self,
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
        logger.info(f"[tool] manage_macro(action={action!r}, name={name!r})")
        if action == "list":
            return {"status": "ok", "macros": self._macro_store.list_macros()}
        if action == "register":
            if not steps:
                return {"status": "error", "reason": "steps が空です"}
            self._macro_store.save_macro(name, steps)
            return {"status": "ok", "message": f"マクロ「{name}」を登録しました"}
        if action == "delete":
            ok = self._macro_store.delete_macro(name)
            return {"status": "ok" if ok else "error",
                    "message": f"マクロ「{name}」を削除しました" if ok else f"マクロ「{name}」が見つかりません"}
        if action == "run":
            stored = self._macro_store.get_macro(name)
            if stored is None:
                return {"status": "error", "reason": f"マクロ「{name}」が登録されていません"}
            return await self.execute_sequence(stored)
        return {"status": "error", "reason": f"不明な action: {action}"}

    def report_unsupported(self, reason: str) -> dict:
        """ユーザーの指示がロボットの能力範囲外の場合に呼び出す。

        Args:
            reason: できない理由の説明（日本語）。
        """
        logger.warning(f"[tool] report_unsupported(reason={reason!r})")
        self._session_store.append_command_log({"event": "unsupported", "reason": reason})
        return {"status": "unsupported", "reason": reason}

    def get_all_tools(self) -> list:
        return [
            self.move_robot,
            self.rotate_robot,
            self.execute_sequence,
            self.observe,
            self.query_status,
            self.query_last_command,
            self.manage_macro,
            self.report_unsupported,
        ]
