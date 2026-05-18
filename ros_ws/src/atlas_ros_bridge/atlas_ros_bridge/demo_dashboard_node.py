from __future__ import annotations

"""Demo dashboard node.

Prints a compact integration dashboard once per second so the final demo feels
like one coherent system instead of disconnected topics.

Subscribes:
- /atlas/demo/telemetry
- /atlas/threat_alerts
- /atlas/commandcenter/status
- /atlas/simulation/status
- /atlas/operator_commands
"""

import json
import time
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class DemoDashboardNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_dashboard_node")

        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("commandcenter_status_topic", "/atlas/commandcenter/status")
        self.declare_parameter("simulation_status_topic", "/atlas/simulation/status")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")

        self._telemetry_topic = self.get_parameter("telemetry_topic").value
        self._alerts_topic = self.get_parameter("alerts_topic").value
        self._cc_status_topic = self.get_parameter("commandcenter_status_topic").value
        self._sim_status_topic = self.get_parameter("simulation_status_topic").value
        self._commands_topic = self.get_parameter("operator_commands_topic").value

        self._last_telemetry: dict[str, Any] | None = None
        self._last_alert: dict[str, Any] | None = None
        self._last_cc_status: dict[str, Any] | None = None
        self._last_sim_status: dict[str, Any] | None = None
        self._last_command: dict[str, Any] | None = None

        self.create_subscription(String, self._telemetry_topic, self._on_telemetry, 10)
        self.create_subscription(String, self._alerts_topic, self._on_alert, 10)
        self.create_subscription(String, self._cc_status_topic, self._on_cc_status, 10)
        self.create_subscription(String, self._sim_status_topic, self._on_sim_status, 10)
        self.create_subscription(String, self._commands_topic, self._on_command, 10)

        self._timer = self.create_timer(1.0, self._print_dashboard)

        self._prev_mission_state: str | None = None
        self._prev_flight_mode: str | None = None
        self._prev_threat: str | None = None
        self._prev_command: str | None = None

        self.get_logger().info("Demo dashboard started")

    def _parse(self, text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _on_telemetry(self, msg: String) -> None:
        self._last_telemetry = self._parse(msg.data)

    def _on_alert(self, msg: String) -> None:
        self._last_alert = self._parse(msg.data)

    def _on_cc_status(self, msg: String) -> None:
        self._last_cc_status = self._parse(msg.data)

    def _on_sim_status(self, msg: String) -> None:
        self._last_sim_status = self._parse(msg.data)

    def _on_command(self, msg: String) -> None:
        self._last_command = self._parse(msg.data)

    def _print_dashboard(self) -> None:
        tel = self._last_telemetry or {}
        mission_state = str(tel.get("mission_state", "-"))
        flight_mode = str(tel.get("flight_mode", "-"))
        wp = tel.get("current_waypoint", "-")
        batt = tel.get("battery_pct", "-")
        lat = tel.get("lat", None)
        lon = tel.get("lon", None)
        alt = tel.get("alt", None)

        pos = "-"
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and isinstance(alt, (int, float)):
            pos = f"lat={lat:.5f}, lon={lon:.5f}, alt={alt:.1f}m"

        last_threat = "-"
        threat_level = None
        if self._last_alert and isinstance(self._last_alert.get("assessments"), list):
            a0 = self._last_alert["assessments"][0] if self._last_alert["assessments"] else None
            if isinstance(a0, dict):
                threat_level = str(a0.get("threat_level", "-")).upper()
                obj_type = str(a0.get("object_type", ""))
                last_threat = f"{threat_level} {obj_type}".strip()

        last_cmd = "-"
        if self._last_command:
            last_cmd = str(self._last_command.get("type", "-"))

        cc_ok = "-"
        if self._last_cc_status:
            cc_ok = str(self._last_cc_status.get("bridge_status", "-"))

        sim_ok = "-"
        if self._last_sim_status:
            sim_ok = str(self._last_sim_status.get("bridge_status", "-"))

        # State transition highlighting (printed inline once per second).
        transitions: list[str] = []
        if self._prev_mission_state is not None and self._prev_mission_state != mission_state:
            transitions.append(f"Mission State: {self._prev_mission_state} -> {mission_state}")
        if self._prev_flight_mode is not None and self._prev_flight_mode != flight_mode:
            transitions.append(f"Flight Mode: {self._prev_flight_mode} -> {flight_mode}")
        if self._prev_threat is not None and self._prev_threat != last_threat and last_threat != "-":
            transitions.append(f"Threat: {self._prev_threat} -> {last_threat}")
        if self._prev_command is not None and self._prev_command != last_cmd and last_cmd != "-":
            transitions.append(f"Command: {self._prev_command} -> {last_cmd}")

        self._prev_mission_state = mission_state
        self._prev_flight_mode = flight_mode
        self._prev_threat = last_threat
        self._prev_command = last_cmd

        # Small "status headline" based on demo phases.
        headline = "ATLAS FINAL DEMO"
        if threat_level in {"HIGH", "MEDIUM"}:
            headline = "ATLAS FINAL DEMO (THREAT)"
        if flight_mode.upper() == "RTL" or mission_state.upper() == "RETURNING_TO_BASE":
            headline = "ATLAS FINAL DEMO (RTL)"
        if mission_state.upper() == "PAUSED" or flight_mode.upper() == "HOLD":
            headline = "ATLAS FINAL DEMO (PAUSED)"

        batt_str = f"{batt:.1f}%" if isinstance(batt, (int, float)) else str(batt)

        lines = [
            f"========== {headline} ==========",
            f"Mission State : {mission_state}",
            f"Flight Mode   : {flight_mode}",
            f"UAV Position  : {pos}",
            f"Battery       : {batt_str}",
            f"Waypoint      : {wp}",
            f"Threat        : {last_threat}",
            f"Last Command  : {last_cmd}",
            f"CommandCenter : {cc_ok}",
            f"Simulation    : {sim_ok}",
        ]

        if transitions:
            lines.append("-- Transitions --------------------")
            lines.extend(transitions)

        lines.append("==================================")

        self.get_logger().info("\n".join(lines))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DemoDashboardNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
