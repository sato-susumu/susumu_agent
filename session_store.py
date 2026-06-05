from __future__ import annotations
import json
import time
from pathlib import Path

SESSION_FILE = Path("session_history.jsonl")
COMMAND_LOG_FILE = Path("command_log.jsonl")
MAX_TURNS = 5
SESSION_TTL_SEC = 86400  # 24時間


def append_command_log(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with COMMAND_LOG_FILE.open("a", encoding="utf-8") as f:
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
