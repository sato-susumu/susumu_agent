from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

SESSION_FILE = Path("session_history.jsonl")
MAX_TURNS = 5
SESSION_TTL_SEC = 86400  # 24時間

# デバッグモード時に set_debug_dir() で上書きされる
_command_log_path: Path | None = None


def set_debug_dir(debug_dir: str) -> None:
    """デバッグモード時に呼び出してコマンドログの出力先を設定する。"""
    global _command_log_path
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    _command_log_path = Path(debug_dir) / f"{ts}_command_log.jsonl"


def append_command_log(entry: dict) -> None:
    if _command_log_path is None:
        return
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _command_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_recent_turns() -> list[dict]:
    if not SESSION_FILE.exists():
        return []
    turns = []
    cutoff = time.time() - SESSION_TTL_SEC
    for line in SESSION_FILE.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if entry.get("ts", 0) > cutoff:
                turns.append(entry)
        except json.JSONDecodeError:
            pass
    return turns[-MAX_TURNS:]


def save_turn(role: str, content: str) -> None:
    entry = {"ts": time.time(), "role": role, "content": content}
    with SESSION_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
