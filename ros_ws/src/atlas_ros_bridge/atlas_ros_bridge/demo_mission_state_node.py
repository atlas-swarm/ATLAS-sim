from __future__ import annotations

"""Demo mission state node for ATLAS final integration demo.

Publishes a coherent multi-UAV simulated telemetry stream on `/atlas/demo/telemetry`.
This is intentionally a bridge/demo-layer component (not core ATLAS logic).

Responsibilities:
- Generate coherent demo telemetry (lat/lon/alt + local x/y/z + heading + battery).
- Simulate a patrol route large enough to be readable in QGC.
- React to `/atlas/operator_commands` (pause/resume/RTL).
- React to `/atlas/demo/runtime_commands` (dashboard buttons).
- Optionally auto-inject a demo threat alert.

The goal is to provide a single shared "source of truth" state that:
- QGroundControl MAVLink bridge can mirror.
- Dashboard can display.
- Gazebo swarm visualizer can follow.
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
class _Vehicle:
    uav_id: str
    x: float
    y: float
    z: float
    heading_deg: float = 0.0
    battery_pct: float = 90.0


@dataclass
class _DemoState:
    mission_id: str = "demo_patrol_001"
    mission_state: str = "RUNNING"  # RUNNING|PAUSED|RETURNING_TO_BASE
    flight_mode: str = "AUTO"  # AUTO|HOLD|RTL
    current_waypoint: int = 0

    speed_mps: float = 10.0
    patrol_scale: float = 1.0

    lead_x: float = 0.0
    lead_y: float = 0.0
    lead_z: float = 20.0
    lead_heading_deg: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class DemoMissionStateNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_mission_state_node")

        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")
        self.declare_parameter("runtime_commands_topic", "/atlas/demo/runtime_commands")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")

        self.declare_parameter("auto_rtl_on_threat", True)
        self.declare_parameter("auto_demo_threat", False)
        self.declare_parameter("threat_delay_s", 120.0)

        self.declare_parameter("num_uavs", 3)
        self.declare_parameter("formation_spacing_m", 80.0)

        telemetry_topic = self.get_parameter("telemetry_topic").get_parameter_value().string_value
        operator_commands_topic = (
            self.get_parameter("operator_commands_topic").get_parameter_value().string_value
        )
        runtime_commands_topic = (
            self.get_parameter("runtime_commands_topic").get_parameter_value().string_value
        )
        alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value

        self._auto_rtl_on_threat = bool(
            self.get_parameter("auto_rtl_on_threat").get_parameter_value().bool_value
        )
        self._auto_demo_threat = bool(
            self.get_parameter("auto_demo_threat").get_parameter_value().bool_value
        )
        self._threat_delay_s = float(self.get_parameter("threat_delay_s").value)

        self._num_uavs = int(self.get_parameter("num_uavs").value)
        self._formation_spacing_m = float(self.get_parameter("formation_spacing_m").value)

        self._telemetry_pub = self.create_publisher(String, telemetry_topic, 10)
        self._alerts_pub = self.create_publisher(String, alerts_topic, 10)

        self._operator_cmd_sub = self.create_subscription(
            String, operator_commands_topic, self._on_operator_command, 10
        )
        self._runtime_cmd_sub = self.create_subscription(
            String, runtime_commands_topic, self._on_runtime_command, 10
        )
        self._alert_sub = self.create_subscription(String, alerts_topic, self._on_alert, 10)

        self._state = _DemoState()
        self._last_tick_s = time.monotonic()
        self._start_s = self._last_tick_s
        self._demo_threat_sent = False

        # Base reference lat/lon for demo (arbitrary but stable).
        self._lat0 = 47.0
        self._lon0 = 8.0

        # Home and demo patrol in local coordinates (meters).
        self._home_x = -120.0
        self._home_y = -120.0
        self._home_z = 20.0

        base_waypoints: list[tuple[float, float, float]] = [
            (0.0, 0.0, 20.0),
            (420.0, 0.0, 24.0),
            (420.0, 260.0, 24.0),
            (0.0, 260.0, 20.0),
        ]
        self._base_waypoints = base_waypoints

        self._timer = self.create_timer(0.1, self._on_timer)  # 10 Hz

        self.get_logger().info(
            "Demo mission state ready. "
            f"telemetry={telemetry_topic} operator_commands={operator_commands_topic} runtime_commands={runtime_commands_topic} "
            f"alerts={alerts_topic} uavs={self._num_uavs} spacing={self._formation_spacing_m}m"
        )

    def _on_timer(self) -> None:
        now_s = time.monotonic()
        dt = max(0.0, min(0.25, now_s - self._last_tick_s))
        self._last_tick_s = now_s

        if self._auto_demo_threat:
            self._maybe_publish_auto_demo_threat(now_s)

        self._step_sim(dt)
        self._publish_telemetry()

    def _maybe_publish_auto_demo_threat(self, now_s: float) -> None:
        if self._demo_threat_sent:
            return
        if (now_s - self._start_s) < max(1.0, self._threat_delay_s):
            return
        self._publish_threat(level="HIGH", object_type="person", reason="auto demo threat")
        self._demo_threat_sent = True
        self.get_logger().warning("Auto demo threat published")

    def _scaled_waypoints(self) -> list[tuple[float, float, float]]:
        scale = _clamp(float(self._state.patrol_scale), 0.25, 4.0)
        out: list[tuple[float, float, float]] = []
        for x, y, z in self._base_waypoints:
            out.append((x * scale, y * scale, z))
        return out

    def _step_sim(self, dt: float) -> None:
        if self._state.mission_state == "PAUSED":
            self._state.flight_mode = "HOLD"
            return

        waypoints = self._scaled_waypoints()

        speed_mps = _clamp(float(self._state.speed_mps), 1.0, 30.0)

        if self._state.flight_mode == "RTL" or self._state.mission_state == "RETURNING_TO_BASE":
            self._state.mission_state = "RETURNING_TO_BASE"
            target = (self._home_x, self._home_y, self._home_z)
        else:
            target = waypoints[self._state.current_waypoint % len(waypoints)]

        dx = target[0] - self._state.lead_x
        dy = target[1] - self._state.lead_y
        dz = target[2] - self._state.lead_z
        dist_xy = math.hypot(dx, dy)
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if dist < 2.0:
            if self._state.mission_state == "RETURNING_TO_BASE":
                self._state.flight_mode = "HOLD"
                self._state.mission_state = "PAUSED"
            else:
                self._state.current_waypoint = (self._state.current_waypoint + 1) % len(waypoints)
            return

        if dist_xy > 1e-6:
            self._state.lead_heading_deg = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0

        step = min(speed_mps * dt, dist)
        if dist > 1e-6:
            self._state.lead_x += (dx / dist) * step
            self._state.lead_y += (dy / dist) * step
            self._state.lead_z += (dz / dist) * step

    def _vehicles(self) -> list[_Vehicle]:
        # A simple, readable line-abreast formation.
        n = max(1, min(6, int(self._num_uavs)))
        spacing = _clamp(float(self._formation_spacing_m), 20.0, 250.0)

        offsets_y: list[float] = []
        if n == 1:
            offsets_y = [0.0]
        else:
            mid = (n - 1) / 2.0
            offsets_y = [((i - mid) * spacing) for i in range(n)]

        vehicles: list[_Vehicle] = []
        for idx, off_y in enumerate(offsets_y, start=1):
            batt = 90.0 - (idx - 1) * 2.5
            vehicles.append(
                _Vehicle(
                    uav_id=f"uav_{idx}",
                    x=float(self._state.lead_x),
                    y=float(self._state.lead_y + off_y),
                    z=float(self._state.lead_z),
                    heading_deg=float(self._state.lead_heading_deg),
                    battery_pct=float(batt),
                )
            )
        return vehicles

    def _publish_telemetry(self) -> None:
        vehicles = self._vehicles()

        # Convert local meters to lat/lon degrees (roughly) for demo.
        lead_lat = self._lat0 + (vehicles[0].y / 111_111.0)
        lead_lon = self._lon0 + (vehicles[0].x / (111_111.0 * math.cos(math.radians(self._lat0))))

        vehicles_payload: list[dict[str, Any]] = []
        for v in vehicles:
            lat = self._lat0 + (v.y / 111_111.0)
            lon = self._lon0 + (v.x / (111_111.0 * math.cos(math.radians(self._lat0))))
            vehicles_payload.append(
                {
                    "uav_id": v.uav_id,
                    "lat": lat,
                    "lon": lon,
                    "alt": v.z,
                    "x": v.x,
                    "y": v.y,
                    "z": v.z,
                    "heading_deg": v.heading_deg,
                    "battery_pct": v.battery_pct,
                }
            )

        payload: dict[str, Any] = {
            "mission_id": self._state.mission_id,
            "mission_state": self._state.mission_state,
            "flight_mode": self._state.flight_mode,
            "current_waypoint": self._state.current_waypoint,
            "speed_mps": self._state.speed_mps,
            "patrol_scale": self._state.patrol_scale,
            "lat": lead_lat,
            "lon": lead_lon,
            "alt": vehicles[0].z,
            "x": vehicles[0].x,
            "y": vehicles[0].y,
            "z": vehicles[0].z,
            "heading_deg": vehicles[0].heading_deg,
            "battery_pct": vehicles[0].battery_pct,
            "vehicles": vehicles_payload,
            "timestamp": int(time.time() * 1000),
        }

        self._telemetry_pub.publish(String(data=json.dumps(payload)))

    def _on_operator_command(self, msg: String) -> None:
        try:
            cmd = json.loads(msg.data)
        except Exception:
            return

        cmd_type = str(cmd.get("type", "")).strip().upper()

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
            mode = str(payload.get("mode", "")).strip().upper()
            if mode == "RTL":
                self._state.flight_mode = "RTL"
                self._state.mission_state = "RETURNING_TO_BASE"

    def _on_runtime_command(self, msg: String) -> None:
        try:
            cmd = json.loads(msg.data)
        except Exception:
            return

        command = str(cmd.get("command", "")).strip().lower()

        if command == "pause":
            self._state.mission_state = "PAUSED"
            return

        if command == "resume":
            self._state.mission_state = "RUNNING"
            self._state.flight_mode = "AUTO"
            return

        if command == "rtl":
            self._state.flight_mode = "RTL"
            self._state.mission_state = "RETURNING_TO_BASE"
            return

        if command == "reset_demo":
            self._state = _DemoState()
            self._demo_threat_sent = False
            self.get_logger().info("Demo state reset")
            return

        if command == "set_speed":
            try:
                self._state.speed_mps = float(cmd.get("value"))
            except Exception:
                return
            return

        if command == "set_patrol_scale":
            try:
                self._state.patrol_scale = float(cmd.get("value"))
            except Exception:
                return
            return

        if command == "trigger_threat":
            level = str(cmd.get("level", "HIGH")).strip().upper() or "HIGH"
            object_type = str(cmd.get("object_type", "person")).strip() or "person"
            reason = str(cmd.get("reason", "dashboard trigger")).strip() or "dashboard trigger"
            self._publish_threat(level=level, object_type=object_type, reason=reason)
            return

        if command == "clear_threat":
            self._publish_clear_threat(source="dashboard")
            return

    def _publish_threat(self, *, level: str, object_type: str, reason: str) -> None:
        level_norm = level.strip().upper()
        if level_norm not in {"LOW", "MEDIUM", "HIGH"}:
            level_norm = "HIGH"

        payload = {
            "source": "demo_mission_state_node",
            "timestamp_ms": int(time.time() * 1000),
            "assessments": [
                {
                    "object_id": "demo_intruder_1",
                    "object_type": object_type,
                    "affiliation": "UNKNOWN",
                    "affiliation_score": 0.75,
                    "behavior_score": 0.9,
                    "final_threat_score": 0.9,
                    "threat_level": level_norm,
                    "reason": reason,
                    "recommended_action": "RTL" if level_norm in {"HIGH", "MEDIUM"} else "MONITOR",
                }
            ],
        }
        self._alerts_pub.publish(String(data=json.dumps(payload)))

    def _publish_clear_threat(self, *, source: str) -> None:
        payload = {
            "source": source,
            "timestamp_ms": int(time.time() * 1000),
            "assessments": [],
            "cleared": True,
        }
        self._alerts_pub.publish(String(data=json.dumps(payload)))

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

        levels = {str(a.get("threat_level", "")).strip().upper() for a in assessments if isinstance(a, dict)}
        if {"HIGH", "MEDIUM"} & levels:
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
