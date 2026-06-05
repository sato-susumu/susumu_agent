from __future__ import annotations
import base64
import time


class CameraClient:
    """カメラ画像取得クライアント。

    simulate モードではダミー画像を返す。
    real モードでは ROS2 Image トピックを購読する。
    """

    def __init__(self, image_topic: str = "/camera/image_raw", mode: str = "simulate"):
        self._topic = image_topic
        self._mode = mode
        self._last_frame: bytes | None = None
        self._last_time: float = 0.0
        self._stale_threshold = 1.0  # 秒
        self._subscriber = None

        if mode == "real":
            self._init_ros2()

    def _init_ros2(self) -> None:
        try:
            import rclpy
            from sensor_msgs.msg import Image
            from rclpy.node import Node
            # 実装時に Node を外部から受け取る形に変更すること
        except ImportError:
            print("  [Camera] rclpy が利用できません。simulate モードに切り替えます。")
            self._mode = "simulate"

    def get_latest_image(self) -> dict:
        if self._mode == "simulate":
            return self._get_dummy_image()
        return self._get_ros2_image()

    def _get_dummy_image(self) -> dict:
        # 1x1 白ピクセルの最小 JPEG を base64 化
        tiny_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xc7"
            b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00"
            b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01"
            b"\x01\x00\x00?\x00\xf5\x00\xff\xd9"
        )
        return {
            "status": "ok",
            "image_base64": base64.b64encode(tiny_jpeg).decode(),
            "timestamp": time.time(),
            "note": "[simulate] ダミー画像です",
        }

    def _get_ros2_image(self) -> dict:
        if self._last_frame is None:
            return {"status": "error", "reason": "カメラトピック未受信"}
        age = time.time() - self._last_time
        if age > self._stale_threshold:
            return {"status": "stale", "reason": f"最新フレームを取得できません（{age:.1f}秒前）"}
        return {
            "status": "ok",
            "image_base64": base64.b64encode(self._last_frame).decode(),
            "timestamp": self._last_time,
        }
