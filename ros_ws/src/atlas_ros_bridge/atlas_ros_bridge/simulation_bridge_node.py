from __future__ import annotations

"""Simulation/status bridge node for ATLAS.

This node provides ROS-side visibility into the ATLAS backend simulation state.
It is intentionally minimal:
- Always publishes a heartbeat/status message.
- Optionally exposes a lightweight snapshot of the most recent WorldState, if available.

It does NOT start or control the SimulationEngine (no ROS logic in core packages).
"""

from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .bridge_utils import make_status_payload, safe_json_dumps


class SimulationBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("simulation_bridge_node")

        self.declare_parameter("simulation_status_topic", "/atlas/simulation/status")
        topic = (
            self.get_parameter("simulation_status_topic").get_parameter_value().string_value
        )

        self._pub = self.create_publisher(String, topic, 10)
        self._timer = self.create_timer(1.0, self._on_timer)

        self.get_logger().info(f"Simulation bridge ready. status={topic}")

    def _read_world_state_snapshot(self) -> dict[str, Any] | None:
        try:
            from atlas_simulation.simulation_engine import SimulationEngine

            engine = SimulationEngine.get_instance()
            world_state = engine.last_world_state
        except Exception as exc:
            return {
                "available": False,
                "error": str(exc),
            }

        if world_state is None:
            return None

        try:
            uav_ids = list(world_state.uav_states.keys())
            return {
                "tick": world_state.tick,
                "timestamp_ms": world_state.timestamp_ms,
                "uav_count": len(uav_ids),
                "uav_ids": uav_ids,
            }
        except Exception as exc:
            return {
                "available": False,
                "error": f"snapshot_failed: {exc}",
            }

    def _on_timer(self) -> None:
        snapshot = self._read_world_state_snapshot()

        extra: dict[str, Any] = {
            "world_state": snapshot,
        }

        payload = make_status_payload(
            node_name=self.get_name(),
            available_features=[
                "heartbeat",
                "world_state_snapshot(optional)",
            ],
            ok=True,
            extra=extra,
        )
        self._pub.publish(String(data=safe_json_dumps(payload)))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SimulationBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
