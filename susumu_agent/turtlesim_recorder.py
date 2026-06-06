"""turtlesim ウィンドウを ffmpeg x11grab で録画するユーティリティ。"""
from __future__ import annotations

import subprocess
import threading
import time

_TURTLESIM_WINDOW_NAME = "TurtleSim"
_FALLBACK_GEOMETRY = "512x512+0+0"  # wmctrl で見つからない場合のフォールバック


def _find_window_geometry() -> str:
    """wmctrl で turtlesim ウィンドウの geometry を "WxH+X+Y" 形式で返す。"""
    try:
        out = subprocess.check_output(
            ["wmctrl", "-lG"], text=True, timeout=5
        )
        for line in out.splitlines():
            if _TURTLESIM_WINDOW_NAME.lower() in line.lower():
                parts = line.split()
                # wmctrl -lG: id desktop x y w h class title
                x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
                # ffmpeg x11grab は偶数サイズが必要
                w = w if w % 2 == 0 else w - 1
                h = h if h % 2 == 0 else h - 1
                return f"{w}x{h}+{x}+{y}"
    except Exception:
        pass
    return _FALLBACK_GEOMETRY


class TurtlesimRecorder:
    """ffmpeg x11grab で turtlesim ウィンドウを録画するクラス。

    start() でバックグラウンドスレッドから ffmpeg を起動し、
    stop() で終了して動画ファイルを確定する。
    """

    def __init__(self, output_path: str, fps: int = 30, display: str = ":0") -> None:
        self.output_path = output_path
        self.fps = fps
        self.display = display
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._launch, daemon=True)
        self._thread.start()
        time.sleep(0.5)  # ffmpeg の起動を少し待つ

    def _launch(self) -> None:
        # ウィンドウ位置を探す（起動直後は描画に時間がかかるため少し待つ）
        time.sleep(1.0)
        geometry = _find_window_geometry()
        size, offset = geometry.split("+", 1) if "+" in geometry else (geometry, "0+0")
        x, y = offset.split("+")

        cmd = [
            "ffmpeg",
            "-f", "x11grab",
            "-framerate", str(self.fps),
            "-video_size", size,
            "-i", f"{self.display}+{x},{y}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-y",
            self.output_path,
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._proc.wait()

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            # ffmpeg はstdin に 'q' を送ると正常終了する
            try:
                self._proc.stdin.write(b"q")
                self._proc.stdin.flush()
            except Exception:
                self._proc.terminate()
        if self._thread:
            self._thread.join(timeout=10)
