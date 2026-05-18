from __future__ import annotations

"""Demo threat event node.

For the final integrated demo we want a deterministic threat alert so:
- commandcenter_bridge_node receives it
- qgc_mavlink_bridge_node sends STATUSTEXT
- demo mission state switches to RTL if auto_rtl_on_threat=true

This node publishes one HIGH threat after a short delay.
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DemoThreatEventNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_threat_event_node")

        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("delay_s", 8.0)

        self._alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value
        self._delay_s = float(self.get_parameter("delay_s").value)

        self._pub = self.create_publisher(String, self._alerts_topic, 10)
        self._start_s = time.monotonic()
        self._sent = False

        self._timer = self.create_timer(0.2, self._on_timer)

        self.get_logger().info(f"Demo threat event will publish HIGH threat after {self._delay_s}s")

    def _on_timer(self) -> None:
        if self._sent:
            return

        if time.monotonic() - self._start_s < self._delay_s:
            return

        payload = {
            "source": "demo_threat_event_node",
            "timestamp_ms": int(time.time() * 1000),
            "assessments": [
                {
                    "object_id": "demo_intruder_1",
                    "object_type": "person",
                    "affiliation": "UNKNOWN",
                    "affiliation_score": 0.75,
                    "behavior_score": 0.9,
                    "final_threat_score": 0.9,
                    "threat_level": "HIGH",
                    "reason": "Demo injected threat after delay",
                }
            ],
        }

        self._pub.publish(String(data=json.dumps(payload)))
        self._sent = True
        self.get_logger().warning("Published demo HIGH threat to /atlas/threat_alerts")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DemoThreatEventNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
