from __future__ import annotations

import threading
import time

import rclpy
from loguru import logger
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

from susumu_agent.demo.commands import DEMO_COMMANDS


class DemoCommandPublisher:
    def __init__(
        self,
        node: Node,
        from_human_topic: str = "/from_human",
        to_human_topic: str = "/to_human",
        response_timeout_sec: float = 90.0,
        interval_sec: float = 1.0,
        final_hold_sec: float = 5.0,
    ) -> None:
        self._node = node
        self._pub = node.create_publisher(String, from_human_topic, 10)
        self._response_event = threading.Event()
        self._response_timeout_sec = response_timeout_sec
        self._interval_sec = interval_sec
        self._final_hold_sec = final_hold_sec
        self._node.create_subscription(String, to_human_topic, self._on_to_human, 10)

    def _on_to_human(self, msg: String) -> None:
        if msg.data.strip():
            logger.info(f"/to_human: {msg.data.strip()}")
            self._response_event.set()

    def _publish_and_wait(self, text: str) -> None:
        self._response_event.clear()
        logger.info(f"/from_human: {text}")
        self._pub.publish(String(data=text))
        if not self._response_event.wait(self._response_timeout_sec):
            logger.warning(f"応答待ちがタイムアウトしました: {text}")
        time.sleep(self._interval_sec)

    def run(self) -> None:
        time.sleep(1.0)
        for demo_cmd in DEMO_COMMANDS:
            self._response_event.clear()
            logger.info(f"/from_human: {demo_cmd.ja}")
            self._pub.publish(String(data=demo_cmd.ja))
            if demo_cmd.interrupt_after_sec > 0:
                time.sleep(demo_cmd.interrupt_after_sec)
                self._publish_and_wait("ストップ")
            elif not self._response_event.wait(self._response_timeout_sec):
                logger.warning(f"応答待ちがタイムアウトしました: {demo_cmd.ja}")
            time.sleep(self._interval_sec)
        if self._final_hold_sec > 0:
            logger.info(f"最終応答後 {self._final_hold_sec:.1f} 秒待ってから終了します。")
            time.sleep(self._final_hold_sec)
        logger.info("デモ入力の配信を完了しました。")


def main() -> None:
    rclpy.init()
    node = Node("susumu_agent_demo_feeder")
    node.declare_parameter("from_human_topic", "/from_human")
    node.declare_parameter("to_human_topic", "/to_human")
    node.declare_parameter("response_timeout_sec", 90.0)
    node.declare_parameter("interval_sec", 1.0)
    node.declare_parameter("final_hold_sec", 5.0)

    from_human_topic = node.get_parameter("from_human_topic").value or "/from_human"
    to_human_topic = node.get_parameter("to_human_topic").value or "/to_human"
    response_timeout_sec = float(node.get_parameter("response_timeout_sec").value)
    interval_sec = float(node.get_parameter("interval_sec").value)
    final_hold_sec = float(node.get_parameter("final_hold_sec").value)

    publisher = DemoCommandPublisher(
        node,
        from_human_topic=from_human_topic,
        to_human_topic=to_human_topic,
        response_timeout_sec=response_timeout_sec,
        interval_sec=interval_sec,
        final_hold_sec=final_hold_sec,
    )
    def _spin() -> None:
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            pass

    spin_thread = threading.Thread(target=_spin, daemon=True)
    spin_thread.start()
    try:
        publisher.run()
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=1.0)
        node.destroy_node()


if __name__ == "__main__":
    main()
