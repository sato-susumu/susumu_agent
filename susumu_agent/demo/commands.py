from __future__ import annotations

from typing import NamedTuple


class DemoCommand(NamedTuple):
    ja: str
    en: str
    interrupt_after_sec: float = 0.0


DEMO_COMMANDS: list[DemoCommand] = [
    DemoCommand("素早く3秒前進して", "Move forward fast for 3 seconds"),
    DemoCommand("右に90度、素早く回転して", "Turn right 90 degrees fast"),
    DemoCommand("素早く3秒前進して", "Move forward fast for 3 seconds"),
    DemoCommand("左に90度、素早く回転して", "Turn left 90 degrees fast"),
    DemoCommand("三角形を描いて。1辺は素早く3秒で移動すること", "Draw a triangle fast (3 sec per side)"),
    DemoCommand("カメラに何が映っている？", "What does the camera see?"),
    DemoCommand(
        "正方形を描いて。1辺は素早く3秒で移動すること",
        "Draw a square fast (3 sec per side)",
        interrupt_after_sec=5.0,
    ),
]


DEMO_COMMAND_BY_TEXT = {
    **{cmd.ja: cmd for cmd in DEMO_COMMANDS},
    "ストップ": DemoCommand("ストップ", "Stop"),
}
