from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

TurnDirection = Literal["left", "right"]

SpeedLevel = Literal["low", "medium", "high"]
Direction = Literal["forward", "backward", "stop"]


class RobotInterface(ABC):
    @abstractmethod
    async def move(self, direction: Direction, speed: SpeedLevel, duration_sec: float) -> None: ...

    @abstractmethod
    async def rotate(self, angle_deg: float, speed: SpeedLevel, continuous: bool = False) -> None: ...

    @abstractmethod
    async def curve(self, direction: Direction, turn: TurnDirection, speed: SpeedLevel, duration_sec: float) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def get_status(self) -> dict: ...
