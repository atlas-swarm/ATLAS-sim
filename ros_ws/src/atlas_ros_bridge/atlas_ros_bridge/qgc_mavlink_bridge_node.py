from __future__ import annotations

"""QGroundControl / MAVLink bridge node for ATLAS.

This node provides a minimal, real MAVLink telemetry and command bridge so that
QGroundControl can act as the operator-side Command Center as described by the
ATLAS low-level design.

Current scope (demo-quality, minimal):
- Broadcast a single simulated UAV via MAVLink over UDP to QGC.
- Subscribe to ATLAS threat alerts and surface them as MAVLink STATUSTEXT.
- Accept basic MAVLink commands (RTL, arm/disarm, set mode) and translate RTL
  into a ROS operator command on /atlas/operator_commands.

The intent is to keep MAVLink / QGC specifics inside atlas_ros_bridge and keep
core ATLAS packages ROS/MAVLink-free.
"""

import json
import math
import time
from dataclasses import dataclass
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .bridge_utils import safe_json_loads


@dataclass
class _VehicleState:
    armed: bool = False
    mode: str = "MANUAL"
    lat_deg: float = 47.0
    lon_deg: float = 8.0
    alt_m: float = 10.0
    yaw_rad: float = 0.0
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    vz_mps: float = 0.0
    battery_percent: int = 90


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _clamp_uint16(value: int) -> int:
    return _clamp_int(int(value), 0, 0xFFFF)


def _clamp_int16(value: int) -> int:
    return _clamp_int(int(value), -0x8000, 0x7FFF)


def _clamp_uint32(value: int) -> int:
    return int(value) & 0xFFFFFFFF


class QGCMavlinkBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("qgc_mavlink_bridge_node")

        self.declare_parameter("qgc_host", "127.0.0.1")
        self.declare_parameter("qgc_port", 14550)
        self.declare_parameter("auto_rtl_on_threat", True)
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")

        self._qgc_host = self.get_parameter("qgc_host").get_parameter_value().string_value
        self._qgc_port = int(self.get_parameter("qgc_port").get_parameter_value().integer_value)
        self._auto_rtl_on_threat = bool(
            self.get_parameter("auto_rtl_on_threat").get_parameter_value().bool_value
        )

        alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value
        operator_commands_topic = (
            self.get_parameter("operator_commands_topic").get_parameter_value().string_value
        )

        self._alerts_sub = self.create_subscription(String, alerts_topic, self._on_threat_alert, 10)
        self._operator_cmd_pub = self.create_publisher(String, operator_commands_topic, 10)

        # Demo telemetry (shared "source of truth" for final integrated demo).
        self.declare_parameter("demo_telemetry_topic", "/atlas/demo/telemetry")
        demo_telemetry_topic = (
            self.get_parameter("demo_telemetry_topic").get_parameter_value().string_value
        )
        self._demo_tel_sub = self.create_subscription(
            String, demo_telemetry_topic, self._on_demo_telemetry, 10
        )
        self._last_demo_tel_s: float | None = None
        self._warned_demo_tel_missing = False

        self._state = _VehicleState()

        self._mav = None
        self._mavlink_init_error: str | None = None
        self._last_hb_s = 0.0
        self._last_pos_s = 0.0
        self._last_status_s = 0.0

        # MAVLink time_boot_ms is uint32 milliseconds since boot; use monotonic time.
        self._boot_time_s = time.monotonic()
        self._start_time_s = self._boot_time_s
        self._startup_grace_s = 2.0

        self._init_mavlink()

        # One timer drives sending telemetry and receiving commands.
        self._timer = self.create_timer(0.05, self._on_timer)  # 20 Hz loop

        self.get_logger().info(
            f"QGC MAVLink bridge ready. udpout:{self._qgc_host}:{self._qgc_port} alerts={alerts_topic}"
        )

    def _time_boot_ms(self) -> int:
        """MAVLink time_boot_ms (uint32): ms since vehicle boot.

        Must not use wall-clock time. Use monotonic and wrap to uint32.
        """
        return int((time.monotonic() - self._boot_time_s) * 1000) & 0xFFFFFFFF

    def _init_mavlink(self) -> None:
        try:
            from pymavlink import mavutil

            # udpout uses an ephemeral local port; QGC can reply to that source port.
            self._mav = mavutil.mavlink_connection(
                f"udpout:{self._qgc_host}:{self._qgc_port}",
                source_system=1,
                source_component=1,
            )
        except Exception as exc:
            self._mavlink_init_error = str(exc)
            self.get_logger().error(f"pymavlink init failed: {exc}")
            self._mav = None

    def _on_timer(self) -> None:
        if self._mav is None:
            return

        # Use monotonic for scheduling and simulated motion.
        # MAVLink time_boot_ms also uses monotonic (see _time_boot_ms).
        now_s = time.monotonic()

        # Receive incoming MAVLink messages (non-blocking).
        self._receive_mavlink()

        # Send heartbeat at 1 Hz.
        if now_s - self._last_hb_s >= 1.0:
            self._send_heartbeat()
            self._last_hb_s = now_s

        # Send position + attitude at ~5 Hz.
        if now_s - self._last_pos_s >= 0.2:
                # If demo telemetry is available, mirror it; otherwise fall back to an internal orbit.
            if self._last_demo_tel_s is None or (now_s - self._last_demo_tel_s) > 2.0:
                # Grace period: allow demo_mission_state_node to come up.
                if (now_s - self._boot_time_s) > self._startup_grace_s and not self._warned_demo_tel_missing:
                    self.get_logger().warning(
                        "No /atlas/demo/telemetry received; using fallback orbit telemetry for QGC"
                    )
                    self._warned_demo_tel_missing = True
                self._update_simulated_motion(now_s)
            else:
                self._warned_demo_tel_missing = False
            self._send_global_position_int(now_s)
            self._send_attitude(now_s)
            self._send_vfr_hud(now_s)
            self._last_pos_s = now_s

        # Send sys_status/battery at 1 Hz.
        if now_s - self._last_status_s >= 1.0:
            self._send_sys_status()
            self._last_status_s = now_s

    def _receive_mavlink(self) -> None:
        assert self._mav is not None

        # Drain a few messages per tick.
        for _ in range(50):
            msg = self._mav.recv_match(blocking=False)
            if msg is None:
                break

            msg_type = msg.get_type()
            if msg_type in ("BAD_DATA", "UNKNOWN"):
                continue

            if msg_type == "COMMAND_LONG":
                self._handle_command_long(msg)
            elif msg_type == "SET_MODE":
                self._handle_set_mode(msg)

    def _handle_command_long(self, msg: Any) -> None:
        # pymavlink provides command in msg.command
        try:
            command = int(msg.command)
        except Exception:
            return

        # MAV_CMD_NAV_RETURN_TO_LAUNCH
        if command == 20:
            self.get_logger().info("Received MAV_CMD_NAV_RETURN_TO_LAUNCH (RTL) from QGC")
            self._set_mode("RTL", source="QGroundControl")
            self._publish_operator_command_rtl(source="QGroundControl")
            self._send_statustext("RTL commanded by QGC")
            return

        # MAV_CMD_COMPONENT_ARM_DISARM
        if command == 400:
            arm = float(getattr(msg, "param1", 0.0))
            self._state.armed = arm >= 0.5
            self._send_statustext(
                "Vehicle armed" if self._state.armed else "Vehicle disarmed"
            )
            return

    def _handle_set_mode(self, msg: Any) -> None:
        # Mode mapping varies by autopilot. Keep minimal: detect base_mode flags.
        # If QGC sends a custom_mode we don't decode here; we just log.
        base_mode = int(getattr(msg, "base_mode", 0))
        custom_mode = int(getattr(msg, "custom_mode", 0))
        self.get_logger().info(f"Received SET_MODE base_mode={base_mode} custom_mode={custom_mode}")

    def _send_heartbeat(self) -> None:
        assert self._mav is not None
        from pymavlink.dialects.v20 import common as mavlink2

        vehicle_type = mavlink2.MAV_TYPE_QUADROTOR
        autopilot = mavlink2.MAV_AUTOPILOT_GENERIC

        base_mode = 0
        if self._state.armed:
            base_mode |= mavlink2.MAV_MODE_FLAG_SAFETY_ARMED

        # Custom mode is autopilot-specific. Keep 0 for demo.
        self._mav.mav.heartbeat_send(
            vehicle_type,
            autopilot,
            base_mode,
            0,
            mavlink2.MAV_STATE_ACTIVE,
        )

    def _send_global_position_int(self, now_s: float) -> None:
        assert self._mav is not None

        # MAVLink expects lat/lon in 1E7 as int32, altitude in mm as int32.
        # Clamp to avoid struct packing crashes if values temporarily exceed range.
        lat = _clamp_int(int(self._state.lat_deg * 1e7), -2147483648, 2147483647)
        lon = _clamp_int(int(self._state.lon_deg * 1e7), -2147483648, 2147483647)
        alt = _clamp_int(int(self._state.alt_m * 1000), -2147483648, 2147483647)

        # Velocity in cm/s as int16.
        vx = _clamp_int(int(self._state.vx_mps * 100), -32768, 32767)
        vy = _clamp_int(int(self._state.vy_mps * 100), -32768, 32767)
        vz = _clamp_int(int(self._state.vz_mps * 100), -32768, 32767)

        # Heading in cdeg as uint16. Use 65535 if unknown.
        hdg = int(((self._state.yaw_rad % (2 * math.pi)) * 180.0 / math.pi) * 100) % 36000
        hdg = _clamp_int(hdg, 0, 35999)

        self._mav.mav.global_position_int_send(
            self._time_boot_ms(),
            lat,
            lon,
            alt,
            alt,
            vx,
            vy,
            vz,
            hdg,
        )

    def _send_attitude(self, now_s: float) -> None:
        assert self._mav is not None
        # MAVLink attitude uses time_boot_ms (uint32) and Euler angles in radians.
        roll = 0.0
        pitch = 0.0
        yaw = float(self._state.yaw_rad)
        self._mav.mav.attitude_send(
            self._time_boot_ms(),
            roll,
            pitch,
            yaw,
            0.0,
            0.0,
            0.0,
        )

    def _send_vfr_hud(self, now_s: float) -> None:
        assert self._mav is not None

        # VFR_HUD provides a human-friendly speed/alt/heading view in QGC.
        airspeed = float(math.hypot(self._state.vx_mps, self._state.vy_mps))
        groundspeed = float(airspeed)
        heading = int(round(math.degrees(self._state.yaw_rad))) % 360

        # No throttle model in the demo yet; keep a safe mid value.
        throttle = int(_clamp_int(50, 0, 100))

        alt = float(self._state.alt_m)
        climb = float(-self._state.vz_mps)

        try:
            self._mav.mav.vfr_hud_send(
                airspeed,
                groundspeed,
                heading,
                throttle,
                alt,
                climb,
            )
        except Exception as exc:
            self.get_logger().warning(f"VFR_HUD send failed: {exc}")

    def _send_sys_status(self) -> None:
        assert self._mav is not None
        # Minimal SYS_STATUS. Field ordering and ranges are strict in MAVLink.
        # battery_remaining is int8: -1 or 0..100.
        onboard_present = _clamp_uint32(0)
        onboard_enabled = _clamp_uint32(0)
        onboard_health = _clamp_uint32(0)

        load = _clamp_uint16(0)  # 0..1000 (0.1% increments)

        voltage_battery_mv = _clamp_uint16(12000)

        # current_battery is int16 in centi-amps. Use -1 if unknown.
        current_battery_cA = _clamp_int16(int(500 / 10))

        battery_remaining = _clamp_int(int(round(self._state.battery_percent)), 0, 100)

        drop_rate_comm = _clamp_uint16(0)
        errors_comm = _clamp_uint16(0)
        errors_count1 = _clamp_uint16(0)
        errors_count2 = _clamp_uint16(0)
        errors_count3 = _clamp_uint16(0)
        errors_count4 = _clamp_uint16(0)

        try:
            self._mav.mav.sys_status_send(
                onboard_present,
                onboard_enabled,
                onboard_health,
                load,
                voltage_battery_mv,
                current_battery_cA,
                int(battery_remaining),
                drop_rate_comm,
                errors_comm,
                errors_count1,
                errors_count2,
                errors_count3,
                errors_count4,
            )
        except Exception as exc:
            self.get_logger().warning(f"SYS_STATUS send failed: {exc}")

    def _send_statustext(self, text: str) -> None:
        assert self._mav is not None
        from pymavlink.dialects.v20 import common as mavlink2

        # STATUSTEXT is max 50 chars.
        msg = text[:50]
        self._mav.mav.statustext_send(mavlink2.MAV_SEVERITY_INFO, msg.encode("utf-8"))

    def _update_simulated_motion(self, now_s: float) -> None:
        # Simple orbit around a reference point.
        t = now_s - self._start_time_s
        radius_m = 20.0
        omega = 0.05  # rad/s

        # Reference lat/lon.
        lat0 = 47.0
        lon0 = 8.0

        x = radius_m * math.cos(omega * t)
        y = radius_m * math.sin(omega * t)

        # Approx meters-to-deg conversion (fine for demo).
        self._state.lat_deg = lat0 + (y / 111_111.0)
        self._state.lon_deg = lon0 + (x / (111_111.0 * math.cos(math.radians(lat0))))

        self._state.vx_mps = -radius_m * omega * math.sin(omega * t)
        self._state.vy_mps = radius_m * omega * math.cos(omega * t)
        self._state.vz_mps = 0.0

        self._state.yaw_rad = math.atan2(self._state.vy_mps, self._state.vx_mps)

    def _on_demo_telemetry(self, msg: String) -> None:
        if self._mav is None:
            return

        tel = safe_json_loads(msg.data, self.get_logger())
        if tel is None:
            return

        # Mirror demo telemetry into MAVLink state.
        try:
            self._state.lat_deg = float(tel.get("lat", self._state.lat_deg))
            self._state.lon_deg = float(tel.get("lon", self._state.lon_deg))
            self._state.alt_m = float(tel.get("alt", self._state.alt_m))

            heading_deg = float(tel.get("heading_deg", 0.0))
            self._state.yaw_rad = math.radians(heading_deg)

            self._state.battery_percent = int(round(float(tel.get("battery_pct", self._state.battery_percent))))

            # Derive a coarse velocity from local x/y if available.
            # This is optional; if missing, keep previous velocities.
            if "x" in tel and "y" in tel:
                # Not a full filter; just uses heading + nominal speed.
                mode = str(tel.get("flight_mode", ""))
                nominal = 4.0 if mode not in ("HOLD", "PAUSED") else 0.0
                self._state.vx_mps = nominal * math.cos(self._state.yaw_rad)
                self._state.vy_mps = nominal * math.sin(self._state.yaw_rad)

            self._last_demo_tel_s = time.monotonic()
        except Exception as exc:
            self.get_logger().warning(f"Failed to apply demo telemetry: {exc}")

    def _on_threat_alert(self, msg: String) -> None:
        if self._mav is None:
            return

        alert = safe_json_loads(msg.data, self.get_logger())
        if alert is None:
            return

        # Surface threat info to QGC.
        self._send_statustext("ATLAS threat alert received")

        if self._auto_rtl_on_threat:
            # Very simple heuristic: if there is at least one assessment with HIGH/MEDIUM,
            # flip state to RTL.
            assessments = alert.get("assessments", [])
            levels = {str(a.get("threat_level", "")).upper() for a in assessments if isinstance(a, dict)}
            if {"HIGH", "MEDIUM"} & levels:
                self._set_mode("RTL", source="ATLAS")
                self._publish_operator_command_rtl(source="ATLAS")
                self._send_statustext("Auto RTL on threat")

    def _set_mode(self, mode: str, source: str) -> None:
        self._state.mode = mode
        self.get_logger().info(f"Mode set to {mode} (source={source})")

    def _publish_operator_command_rtl(self, source: str) -> None:
        payload = {
            "type": "ISSUE_OVERRIDE",
            "payload": {
                "mode": "RTL",
                "target_uav": "uav_1",
                "source": source,
            },
        }
        self._operator_cmd_pub.publish(String(data=json.dumps(payload)))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = QGCMavlinkBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
