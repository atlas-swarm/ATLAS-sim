from __future__ import annotations

"""Demo mission state node for ATLAS final integration demo.

Publishes a single simulated UAV telemetry stream on /atlas/demo/telemetry.
This is intentionally a bridge/demo-layer component (not core ATLAS logic).

Responsibilities:
- Generate coherent demo telemetry (lat/lon/alt + local x/y/z + heading + battery).
- Simulate a simple waypoint patrol.
- React to /atlas/operator_commands (PAUSE_MISSION, ISSUE_OVERRIDE RTL).
- Optionally react to /atlas/threat_alerts (auto RTL on threat).

The goal is to provide a single shared "source of truth" state that:
- QGroundControl MAVLink bridge can mirror.
- Dashboard can display.
- Operator commands can influence.
"""

import json
import math
import time
from dataclasses import dataclass
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


@dataclass
class _DemoState:
    mission_id: str = "demo_patrol_001"
    uav_id: str = "uav_1"
    # Local ENU-ish demo coordinates (meters)
    x: float = 0.0
    y: float = 0.0
    z: float = 10.0
    heading_deg: float = 0.0
    battery_pct: float = 90.0
    flight_mode: str = "AUTO"
    mission_state: str = "RUNNING"  # RUNNING|PAUSED|RETURNING_TO_BASE
    current_waypoint: int = 0


class DemoMissionStateNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_mission_state_node")

        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("auto_rtl_on_threat", True)

        telemetry_topic = self.get_parameter("telemetry_topic").get_parameter_value().string_value
        commands_topic = (
            self.get_parameter("operator_commands_topic").get_parameter_value().string_value
        )
        alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value

        self._auto_rtl_on_threat = bool(
            self.get_parameter("auto_rtl_on_threat").get_parameter_value().bool_value
        )

        self._telemetry_pub = self.create_publisher(String, telemetry_topic, 10)
        self._cmd_sub = self.create_subscription(String, commands_topic, self._on_command, 10)
        self._alert_sub = self.create_subscription(String, alerts_topic, self._on_alert, 10)

        self._state = _DemoState()
        self._last_tick_s = time.monotonic()

        # Base "home" in local coordinates.
        self._home_x = 0.0
        self._home_y = 0.0
        self._home_z = 10.0

        # Base reference lat/lon for demo (arbitrary but stable).
        self._lat0 = 47.0
        self._lon0 = 8.0

        # Simple square-ish patrol.
        self._waypoints: list[tuple[float, float, float]] = [
            (0.0, 0.0, 10.0),
            (30.0, 0.0, 12.0),
            (30.0, 20.0, 12.0),
            (0.0, 20.0, 10.0),
        ]

        self._timer = self.create_timer(0.1, self._on_timer)  # 10 Hz

        self.get_logger().info(
            f"Demo mission state publishing on {telemetry_topic} (commands={commands_topic}, alerts={alerts_topic})"
        )

    def _on_timer(self) -> None:
        now_s = time.monotonic()
        dt = max(0.0, min(0.2, now_s - self._last_tick_s))
        self._last_tick_s = now_s

        self._step_sim(dt)
        self._publish_telemetry()

    def _step_sim(self, dt: float) -> None:
        # Battery drain (slow).
        self._state.battery_pct = max(0.0, self._state.battery_pct - dt * 0.02)

        if self._state.mission_state == "PAUSED":
            self._state.flight_mode = "HOLD"
            return

        speed_mps = 4.0

        if self._state.flight_mode == "RTL" or self._state.mission_state == "RETURNING_TO_BASE":
            self._state.mission_state = "RETURNING_TO_BASE"
            target = (self._home_x, self._home_y, self._home_z)
        else:
            target = self._waypoints[self._state.current_waypoint % len(self._waypoints)]

        dx = target[0] - self._state.x
        dy = target[1] - self._state.y
        dz = target[2] - self._state.z
        dist_xy = math.hypot(dx, dy)
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if dist < 0.8:
            if self._state.mission_state == "RETURNING_TO_BASE":
                self._state.flight_mode = "HOLD"
                self._state.mission_state = "PAUSED"
            else:
                self._state.current_waypoint = (self._state.current_waypoint + 1) % len(self._waypoints)
            return

        # Move toward target.
        if dist_xy > 1e-6:
            self._state.heading_deg = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0

        step = min(speed_mps * dt, dist)
        if dist > 1e-6:
            self._state.x += (dx / dist) * step
            self._state.y += (dy / dist) * step
            self._state.z += (dz / dist) * step

    def _publish_telemetry(self) -> None:
        # Convert local meters to lat/lon degrees (roughly) for demo.
        lat = self._lat0 + (self._state.y / 111_111.0)
        lon = self._lon0 + (self._state.x / (111_111.0 * math.cos(math.radians(self._lat0))))

        payload: dict[str, Any] = {
            "mission_id": self._state.mission_id,
            "uav_id": self._state.uav_id,
            "lat": lat,
            "lon": lon,
            "alt": self._state.z,
            "x": self._state.x,
            "y": self._state.y,
            "z": self._state.z,
            "heading_deg": self._state.heading_deg,
            "battery_pct": self._state.battery_pct,
            "flight_mode": self._state.flight_mode,
            "mission_state": self._state.mission_state,
            "current_waypoint": self._state.current_waypoint,
            "timestamp": int(time.time() * 1000),
        }

        self._telemetry_pub.publish(String(data=json.dumps(payload)))

    def _on_command(self, msg: String) -> None:
        try:
            cmd = json.loads(msg.data)
        except Exception:
            return

        cmd_type = str(cmd.get("type", "")).upper()

        if cmd_type == "PAUSE_MISSION":
            self._state.mission_state = "PAUSED"
            return

        if cmd_type == "RESUME_MISSION":
            self._state.mission_state = "RUNNING"
            self._state.flight_mode = "AUTO"
            return

        if cmd_type == "ABORT_MISSION":
            self._state.flight_mode = "RTL"
            self._state.mission_state = "RETURNING_TO_BASE"
            return

        if cmd_type == "ISSUE_OVERRIDE":
            payload = cmd.get("payload", {})
            mode = str(payload.get("mode", "")).upper()
            if mode == "RTL":
                self._state.flight_mode = "RTL"
                self._state.mission_state = "RETURNING_TO_BASE"

    def _on_alert(self, msg: String) -> None:
        if not self._auto_rtl_on_threat:
            return

        try:
            alert = json.loads(msg.data)
        except Exception:
            return

        assessments = alert.get("assessments", [])
        if not isinstance(assessments, list):
            return

        levels = {str(a.get("threat_level", "")).upper() for a in assessments if isinstance(a, dict)}
        if {"HIGH", "MEDIUM"} & levels:
            # Directly switch to RTL (and dashboard/QGC will reflect it via telemetry).
            self._state.flight_mode = "RTL"
            self._state.mission_state = "RETURNING_TO_BASE"


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DemoMissionStateNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
