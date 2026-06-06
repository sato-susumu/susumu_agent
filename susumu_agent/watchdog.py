from __future__ import annotations

import threading

from loguru import logger

from susumu_agent.shared_state import get_state


class Watchdog:
    """指定秒間コマンドがなければ自動停止する。"""

    def __init__(self, timeout_sec: float = 5.0):
        self._timeout = timeout_sec
        self._thread = threading.Thread(target=self._run, daemon=True, name="watchdog")

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        state = get_state()
        while not state.shutdown_event.wait(timeout=1.0):
            if state.is_active and state.get_last_command_age() > self._timeout:
                logger.warning(f"[Watchdog] {self._timeout}秒間コマンドなし → 自動停止")
                state.zero_twist()
                state.stop_event.set()
