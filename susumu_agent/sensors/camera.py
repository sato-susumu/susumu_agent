from __future__ import annotations

import base64
import threading
import time

from loguru import logger


class CameraClient:
    """カメラ画像取得クライアント。

    simulate モードではダミー画像を返す。
    real モードでは ROS2 Image トピックを購読する。
    """

    def __init__(
        self,
        image_topic: str = "/camera/image_raw",
        mode: str = "simulate",
        node=None,
    ):
        self._topic = image_topic
        self._mode = mode
        self._last_frame: bytes | None = None
        self._last_time: float = 0.0
        self._lock = threading.Lock()
        self._stale_threshold = 1.0  # 秒

        if mode == "real" and node is not None:
            self._init_ros2(node)

    def _init_ros2(self, node) -> None:
        try:
            import cv2  # noqa: PLC0415
            from cv_bridge import CvBridge  # noqa: PLC0415
            from sensor_msgs.msg import Image  # noqa: PLC0415
            bridge = CvBridge()

            def _callback(msg: Image) -> None:
                try:
                    cv_img = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                    ok, buf = cv2.imencode(".jpg", cv_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        with self._lock:
                            self._last_frame = buf.tobytes()
                            self._last_time = time.time()
                except Exception as exc:
                    # ROS2 サブスクリプション callback が例外で死ぬとトピック受信が止まるため捕捉する
                    logger.warning(f"camera callback error: {exc}")

            node.create_subscription(Image, self._topic, _callback, 10)
        except ImportError:
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
        with self._lock:
            frame = self._last_frame
            last_time = self._last_time
        if frame is None:
            return {"status": "error", "reason": "カメラトピック未受信"}
        age = time.time() - last_time
        if age > self._stale_threshold:
            return {"status": "stale", "reason": f"最新フレームを取得できません（{age:.1f}秒前）"}
        return {
            "status": "ok",
            "image_base64": base64.b64encode(frame).decode(),
            "timestamp": last_time,
        }
