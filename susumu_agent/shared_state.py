from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TwistValue:
    linear_x: float = 0.0
    angular_z: float = 0.0


@dataclass
class SharedState:
    _twist: TwistValue = field(default_factory=TwistValue)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    shutdown_event: threading.Event = field(default_factory=threading.Event)
    last_command: dict | None = None
    last_command_time: float = field(default_factory=time.monotonic)
    _is_active: bool = False

    _instance: SharedState | None = field(default=None, init=False, repr=False, compare=False)

    def set_twist(self, linear_x: float, angular_z: float) -> None:
        with self._lock:
            self._twist = TwistValue(linear_x, angular_z)
            self.last_command_time = time.monotonic()
            self._is_active = (linear_x != 0.0 or angular_z != 0.0)

    def get_twist(self) -> TwistValue:
        with self._lock:
            return TwistValue(self._twist.linear_x, self._twist.angular_z)

    def zero_twist(self) -> None:
        with self._lock:
            self._twist = TwistValue()
            self._is_active = False

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    def get_last_command_age(self) -> float:
        with self._lock:
            return time.monotonic() - self.last_command_time

    @classmethod
    def instance(cls) -> SharedState:
        """プロセス内シングルトンを返す。"""
        if not hasattr(cls, "_singleton") or cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton


# 後方互換エイリアス
def get_state() -> SharedState:
    return SharedState.instance()
