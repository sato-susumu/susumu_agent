from __future__ import annotations

import datetime
import json
import time
from pathlib import Path


class SessionStore:
    _MAX_TURNS = 5
    _SESSION_TTL_SEC = 86400

    def __init__(self, session_file: Path | None = None) -> None:
        self._session_file = session_file or Path.home() / ".susumu_agent" / "session_history.jsonl"
        self._command_log_path: Path | None = None

    def set_debug_dir(self, debug_dir: str) -> None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._command_log_path = Path(debug_dir) / f"{ts}_command_log.jsonl"

    def append_command_log(self, entry: dict) -> None:
        if self._command_log_path is None:
            return
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._command_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def load_recent_turns(self) -> list[dict]:
        if not self._session_file.exists():
            return []
        turns = []
        cutoff = time.time() - self._SESSION_TTL_SEC
        for line in self._session_file.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                if entry.get("ts", 0) > cutoff:
                    turns.append(entry)
            except json.JSONDecodeError:
                pass
        return turns[-self._MAX_TURNS:]

    def save_turn(self, role: str, content: str) -> None:
        entry = {"ts": time.time(), "role": role, "content": content}
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        with self._session_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
