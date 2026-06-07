from __future__ import annotations

import json
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
        agent_event_topic: str = "/agent_event",
        response_timeout_sec: float = 90.0,
        interval_sec: float = 1.0,
        final_hold_sec: float = 5.0,
    ) -> None:
        self._node = node
        self._pub = node.create_publisher(String, from_human_topic, 10)
        self._completed_event = threading.Event()
        self._response_timeout_sec = response_timeout_sec
        self._interval_sec = interval_sec
        self._final_hold_sec = final_hold_sec
        self._pending_interrupt_text: str | None = None
        self._interrupt_delay_sec: float = 0.0
        self._interrupt_triggered: bool = False
        self._interrupt_thread: threading.Thread | None = None
        self._interrupt_lock = threading.Lock()
        self._node.create_subscription(String, agent_event_topic, self._on_agent_event, 10)

    def _on_agent_event(self, msg: String) -> None:
        text = msg.data.strip()
        if not text:
            return
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return
        event_type = event.get("type", "")
        logger.info(f"[/agent_event] {json.dumps(event, ensure_ascii=False)}")
        if event_type == "tool_start" and self._pending_interrupt_text:
            with self._interrupt_lock:
                if not self._interrupt_triggered:
                    self._interrupt_triggered = True
                    self._interrupt_thread = threading.Thread(target=self._delayed_interrupt, daemon=True)
                    self._interrupt_thread.start()
        if event_type == "action_completed":
            self._completed_event.set()

    def _delayed_interrupt(self) -> None:
        time.sleep(self._interrupt_delay_sec)
        if self._pending_interrupt_text:
            text = self._pending_interrupt_text
            self._pending_interrupt_text = None
            self._publish_and_wait(text)

    def _publish_and_wait(self, text: str) -> None:
        self._completed_event.clear()
        logger.info(f"[/from_human] {text}")
        self._pub.publish(String(data=text))
        if not self._completed_event.wait(self._response_timeout_sec):
            logger.warning(f"完了待ちがタイムアウトしました: {text}")
        self._completed_event.clear()
        time.sleep(self._interval_sec)

    def run(self) -> None:
        time.sleep(1.0)
        for demo_cmd in DEMO_COMMANDS:
            self._completed_event.clear()
            if demo_cmd.interrupt_after_sec > 0:
                self._pending_interrupt_text = demo_cmd.interrupt_text
                self._interrupt_delay_sec = demo_cmd.interrupt_after_sec
                self._interrupt_triggered = False
            else:
                self._pending_interrupt_text = None
                self._interrupt_delay_sec = 0.0
                self._interrupt_triggered = False
            logger.info(f"[/from_human] {demo_cmd.ja}")
            self._pub.publish(String(data=demo_cmd.ja))
            if not self._completed_event.wait(self._response_timeout_sec):
                logger.warning(f"完了待ちがタイムアウトしました: {demo_cmd.ja}")
            if self._interrupt_thread is not None:
                self._interrupt_thread.join(timeout=self._response_timeout_sec)
                self._interrupt_thread = None
            time.sleep(self._interval_sec)
        if self._final_hold_sec > 0:
            time.sleep(self._final_hold_sec)
        logger.info("デモ入力の配信を完了しました。")


def main() -> None:
    rclpy.init()
    node = Node("susumu_agent_demo_feeder")
    node.declare_parameter("from_human_topic", "/from_human")
    node.declare_parameter("agent_event_topic", "/agent_event")
    node.declare_parameter("response_timeout_sec", 90.0)
    node.declare_parameter("interval_sec", 1.0)
    node.declare_parameter("final_hold_sec", 5.0)

    from_human_topic = node.get_parameter("from_human_topic").value or "/from_human"
    agent_event_topic = node.get_parameter("agent_event_topic").value or "/agent_event"
    response_timeout_sec = float(node.get_parameter("response_timeout_sec").value)
    interval_sec = float(node.get_parameter("interval_sec").value)
    final_hold_sec = float(node.get_parameter("final_hold_sec").value)

    publisher = DemoCommandPublisher(
        node,
        from_human_topic=from_human_topic,
        agent_event_topic=agent_event_topic,
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
