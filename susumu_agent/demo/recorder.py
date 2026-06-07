"""turtlesim ウィンドウを ffmpeg x11grab で録画するユーティリティ。"""
from __future__ import annotations

import subprocess
import threading
import time


class TurtlesimRecorder:
    """ffmpeg x11grab で turtlesim ウィンドウを録画するクラス。"""

    _WINDOW_NAME = "TurtleSim"
    _FALLBACK_GEOMETRY = "512x512+0+0"

    def __init__(self, output_path: str, fps: int = 30, display: str = ":0") -> None:
        self.output_path = output_path
        self.fps = fps
        self.display = display
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def _find_window_geometry(self) -> str:
        # xwininfo を優先して使用（描画領域の正確な座標を返す）
        try:
            out = subprocess.check_output(
                ["xwininfo", "-name", self._WINDOW_NAME], text=True, timeout=5
            )
            vals: dict[str, int] = {}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Absolute upper-left X:"):
                    vals["x"] = int(line.split()[-1])
                elif line.startswith("Absolute upper-left Y:"):
                    vals["y"] = int(line.split()[-1])
                elif line.startswith("Width:"):
                    vals["w"] = int(line.split()[-1])
                elif line.startswith("Height:"):
                    vals["h"] = int(line.split()[-1])
            if len(vals) == 4:
                w = vals["w"] if vals["w"] % 2 == 0 else vals["w"] - 1
                h = vals["h"] if vals["h"] % 2 == 0 else vals["h"] - 1
                return f"{w}x{h}+{vals['x']}+{vals['y']}"
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return self._FALLBACK_GEOMETRY

    def start(self) -> None:
        self._thread = threading.Thread(target=self._launch, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def _launch(self) -> None:
        time.sleep(1.0)
        geometry = self._find_window_geometry()
        size, offset = geometry.split("+", 1) if "+" in geometry else (geometry, "0+0")
        x, y = offset.split("+")
        cmd = [
            "ffmpeg", "-f", "x11grab",
            "-framerate", str(self.fps),
            "-video_size", size,
            "-i", f"{self.display}+{x},{y}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-y", self.output_path,
        ]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._proc.wait()

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(b"q")
                self._proc.stdin.flush()
            except OSError:
                self._proc.terminate()
        if self._thread:
            self._thread.join(timeout=10)
