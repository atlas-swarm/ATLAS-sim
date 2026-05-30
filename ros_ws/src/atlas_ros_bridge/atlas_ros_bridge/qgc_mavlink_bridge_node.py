from __future__ import annotations

"""QGroundControl / MAVLink bridge node for ATLAS.

This node provides a minimal, real MAVLink telemetry + command bridge so that
QGroundControl can be used as a demo-friendly "operator view".

Demo scope (intentionally lightweight; not a PX4 stack):
- Broadcast multiple simulated vehicles via MAVLink over UDP to QGC.
- Mirror the shared demo source-of-truth topic `/atlas/demo/telemetry`.
- Surface ATLAS threat alerts as MAVLink STATUSTEXT.
- Accept basic MAVLink commands (RTL) and publish an ATLAS operator command.

Why QGC may still show "Not Ready":
- This is not a full autopilot; we provide essential telemetry only.
- We do, however, publish GPS + system status so QGC is as readable as possible.
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
    uav_id: str
    lat_deg: float = 47.0
    lon_deg: float = 8.0
    alt_m: float = 20.0
    yaw_rad: float = 0.0
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    vz_mps: float = 0.0
    battery_percent: int = 90

    armed: bool = True
    mode: str = "AUTO"

    home_sent: bool = False


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

        # Demo telemetry (shared "source of truth" for final demo).
        self.declare_parameter("demo_telemetry_topic", "/atlas/demo/telemetry")
        demo_telemetry_topic = self.get_parameter("demo_telemetry_topic").get_parameter_value().string_value
        self._demo_tel_sub = self.create_subscription(String, demo_telemetry_topic, self._on_demo_telemetry, 10)
        self._last_demo_tel_s: float | None = None

        self._vehicles: dict[int, _VehicleState] = {}

        self._mav = None
        self._mavlink_init_error: str | None = None

        self._last_hb_s = 0.0
        self._last_pos_s = 0.0
        self._last_status_s = 0.0

        # MAVLink time_boot_ms uses monotonic time.
        self._boot_time_s = time.monotonic()
        self._start_time_s = self._boot_time_s
        self._startup_grace_s = 2.0
        self._warned_demo_tel_missing = False

        self._init_mavlink()

        # One timer drives sending telemetry and receiving commands.
        self._timer = self.create_timer(0.05, self._on_timer)  # 20 Hz loop

        self.get_logger().info(
            f"QGC MAVLink bridge ready. udpout:{self._qgc_host}:{self._qgc_port} alerts={alerts_topic}"
        )

    def _time_boot_ms(self) -> int:
        return int((time.monotonic() - self._boot_time_s) * 1000) & 0xFFFFFFFF

    def _init_mavlink(self) -> None:
        try:
            from pymavlink import mavutil

            self._mav = mavutil.mavlink_connection(
                f"udpout:{self._qgc_host}:{self._qgc_port}",
                source_system=1,
                source_component=1,
            )
        except Exception as exc:
            self._mavlink_init_error = str(exc)
            self.get_logger().error(f"pymavlink init failed: {exc}")
            self._mav = None

    def _with_sysid(self, sysid: int, fn) -> None:
        if self._mav is None:
            return

        prev = int(getattr(self._mav.mav, "srcSystem", 1))
        self._mav.mav.srcSystem = int(sysid)
        try:
            fn()
        finally:
            self._mav.mav.srcSystem = prev

    def _on_timer(self) -> None:
        if self._mav is None:
            return

        now_s = time.monotonic()

        self._receive_mavlink()

        vehicles = self._vehicles
        if not vehicles:
            # If demo telemetry is missing, fall back to a readable 3-UAV orbit.
            if self._last_demo_tel_s is None or (now_s - self._last_demo_tel_s) > 2.0:
                if (now_s - self._boot_time_s) > self._startup_grace_s and not self._warned_demo_tel_missing:
                    self.get_logger().warning(
                        "No /atlas/demo/telemetry received; using fallback orbit telemetry for QGC"
                    )
                    self._warned_demo_tel_missing = True
                self._vehicles = self._fallback_orbit(now_s)
                vehicles = self._vehicles

        # Heartbeat at 1 Hz.
        if now_s - self._last_hb_s >= 1.0:
            for sysid, st in vehicles.items():
                self._with_sysid(sysid, lambda st=st: self._send_heartbeat(st))
            self._last_hb_s = now_s

        # Position at ~5 Hz.
        if now_s - self._last_pos_s >= 0.2:
            for sysid, st in vehicles.items():
                self._with_sysid(sysid, lambda st=st: self._send_pose_bundle(st))
            self._last_pos_s = now_s

        # Status/GPS at 1 Hz.
        if now_s - self._last_status_s >= 1.0:
            for sysid, st in vehicles.items():
                self._with_sysid(sysid, lambda st=st: self._send_status_bundle(st))
            self._last_status_s = now_s

    def _receive_mavlink(self) -> None:
        assert self._mav is not None

        for _ in range(80):
            msg = self._mav.recv_match(blocking=False)
            if msg is None:
                break

            msg_type = msg.get_type()
            if msg_type in ("BAD_DATA", "UNKNOWN"):
                continue

            if msg_type == "COMMAND_LONG":
                self._handle_command_long(msg)

    def _handle_command_long(self, msg: Any) -> None:
        try:
            command = int(msg.command)
        except Exception:
            return

        target_sys = int(getattr(msg, "target_system", 1) or 1)
        st = self._vehicles.get(target_sys)
        uav_id = st.uav_id if st is not None else "uav_1"

        # MAV_CMD_NAV_RETURN_TO_LAUNCH
        if command == 20:
            self.get_logger().info(f"Received RTL from QGC (sysid={target_sys} -> {uav_id})")
            self._publish_operator_command_rtl(target_uav=uav_id, source="QGroundControl")
            self._send_statustext(f"RTL commanded by QGC ({uav_id})")
            return

        # MAV_CMD_COMPONENT_ARM_DISARM
        if command == 400:
            arm = float(getattr(msg, "param1", 0.0))
            st = self._vehicles.get(target_sys)
            if st is not None:
                st.armed = arm >= 0.5
            return

    def _send_heartbeat(self, st: _VehicleState) -> None:
        assert self._mav is not None
        from pymavlink.dialects.v20 import common as mavlink2

        vehicle_type = mavlink2.MAV_TYPE_QUADROTOR
        autopilot = mavlink2.MAV_AUTOPILOT_GENERIC

        base_mode = 0
        if st.armed:
            base_mode |= mavlink2.MAV_MODE_FLAG_SAFETY_ARMED

        self._mav.mav.heartbeat_send(
            vehicle_type,
            autopilot,
            base_mode,
            0,
            mavlink2.MAV_STATE_ACTIVE,
        )

    def _send_pose_bundle(self, st: _VehicleState) -> None:
        self._send_global_position_int(st)
        self._send_attitude(st)
        self._send_vfr_hud(st)

        if not st.home_sent:
            self._send_home_position(st)
            st.home_sent = True

    def _send_status_bundle(self, st: _VehicleState) -> None:
        self._send_sys_status(st)
        self._send_gps_raw_int(st)

    def _send_global_position_int(self, st: _VehicleState) -> None:
        assert self._mav is not None

        time_boot_ms = _clamp_uint32(self._time_boot_ms())
        lat = int(st.lat_deg * 1e7)
        lon = int(st.lon_deg * 1e7)
        alt_mm = int(st.alt_m * 1000)

        vx = _clamp_int16(int(st.vx_mps * 100))
        vy = _clamp_int16(int(st.vy_mps * 100))
        vz = _clamp_int16(int(st.vz_mps * 100))

        heading_cdeg = _clamp_uint16(int((math.degrees(st.yaw_rad) % 360.0) * 100))

        try:
            self._mav.mav.global_position_int_send(
                time_boot_ms,
                lat,
                lon,
                alt_mm,
                alt_mm,
                vx,
                vy,
                vz,
                heading_cdeg,
            )
        except Exception as exc:
            self.get_logger().warning(f"GLOBAL_POSITION_INT send failed: {exc}")

    def _send_attitude(self, st: _VehicleState) -> None:
        assert self._mav is not None

        time_boot_ms = _clamp_uint32(self._time_boot_ms())
        roll = 0.0
        pitch = 0.0
        yaw = float(st.yaw_rad)

        try:
            self._mav.mav.attitude_send(time_boot_ms, roll, pitch, yaw, 0.0, 0.0, 0.0)
        except Exception as exc:
            self.get_logger().warning(f"ATTITUDE send failed: {exc}")

    def _send_vfr_hud(self, st: _VehicleState) -> None:
        assert self._mav is not None

        groundspeed = math.hypot(st.vx_mps, st.vy_mps)
        airspeed = groundspeed
        heading = int(math.degrees(st.yaw_rad) % 360.0)
        throttle = 60
        alt = float(st.alt_m)
        climb = float(-st.vz_mps)

        try:
            self._mav.mav.vfr_hud_send(airspeed, groundspeed, heading, throttle, alt, climb)
        except Exception as exc:
            self.get_logger().warning(f"VFR_HUD send failed: {exc}")

    def _send_sys_status(self, st: _VehicleState) -> None:
        assert self._mav is not None

        battery_remaining = _clamp_int(int(st.battery_percent), 0, 100)
        voltage_battery = 12_000
        current_battery = -1

        try:
            self._mav.mav.sys_status_send(
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                voltage_battery,
                current_battery,
                battery_remaining,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        except Exception as exc:
            self.get_logger().warning(f"SYS_STATUS send failed: {exc}")

    def _send_gps_raw_int(self, st: _VehicleState) -> None:
        assert self._mav is not None

        # Provide a basic GPS fix so QGC can be more readable.
        time_usec = int(time.time() * 1e6)
        fix_type = 3
        lat = int(st.lat_deg * 1e7)
        lon = int(st.lon_deg * 1e7)
        alt_mm = int(st.alt_m * 1000)

        eph = 80
        epv = 120
        vel = int(math.hypot(st.vx_mps, st.vy_mps) * 100)
        cog = int((math.degrees(st.yaw_rad) % 360.0) * 100)
        satellites_visible = 10

        try:
            self._mav.mav.gps_raw_int_send(
                time_usec,
                fix_type,
                lat,
                lon,
                alt_mm,
                eph,
                epv,
                vel,
                cog,
                satellites_visible,
            )
        except Exception as exc:
            self.get_logger().warning(f"GPS_RAW_INT send failed: {exc}")

    def _send_home_position(self, st: _VehicleState) -> None:
        assert self._mav is not None

        lat = int(st.lat_deg * 1e7)
        lon = int(st.lon_deg * 1e7)
        alt_mm = int(st.alt_m * 1000)

        try:
            self._mav.mav.home_position_send(
                lat,
                lon,
                alt_mm,
                0.0,
                0.0,
                0.0,
                (0.0, 0.0, 0.0, 0.0),
                0.0,
                0.0,
                0.0,
            )
        except Exception as exc:
            self.get_logger().warning(f"HOME_POSITION send failed: {exc}")

    def _send_statustext(self, text: str) -> None:
        assert self._mav is not None
        from pymavlink.dialects.v20 import common as mavlink2

        msg = text[:50]
        self._mav.mav.statustext_send(mavlink2.MAV_SEVERITY_INFO, msg.encode("utf-8"))

    def _fallback_orbit(self, now_s: float) -> dict[int, _VehicleState]:
        t = now_s - self._start_time_s
        omega = 0.015
        base_radius = 140.0

        lat0 = 47.0
        lon0 = 8.0

        out: dict[int, _VehicleState] = {}
        for idx in (1, 2, 3):
            radius_m = base_radius + (idx - 1) * 40.0
            phase = (idx - 1) * (2 * math.pi / 3)

            x = radius_m * math.cos(omega * t + phase)
            y = radius_m * math.sin(omega * t + phase)

            lat = lat0 + (y / 111_111.0)
            lon = lon0 + (x / (111_111.0 * math.cos(math.radians(lat0))))

            vx = -radius_m * omega * math.sin(omega * t + phase)
            vy = radius_m * omega * math.cos(omega * t + phase)

            yaw = math.atan2(vy, vx)

            out[idx] = _VehicleState(
                uav_id=f"uav_{idx}",
                lat_deg=lat,
                lon_deg=lon,
                alt_m=24.0,
                yaw_rad=yaw,
                vx_mps=vx,
                vy_mps=vy,
                vz_mps=0.0,
                battery_percent=90 - (idx - 1) * 2,
            )
        return out

    def _on_demo_telemetry(self, msg: String) -> None:
        if self._mav is None:
            return

        tel = safe_json_loads(msg.data, self.get_logger())
        if tel is None:
            return

        vehicles = tel.get("vehicles")
        if not isinstance(vehicles, list) or not vehicles:
            vehicles = [tel]

        out: dict[int, _VehicleState] = {}

        speed_mps = None
        try:
            speed_mps = float(tel.get("speed_mps"))
        except Exception:
            speed_mps = None

        for idx, item in enumerate(vehicles, start=1):
            if not isinstance(item, dict):
                continue

            uav_id = str(item.get("uav_id", f"uav_{idx}")).strip() or f"uav_{idx}"
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
                alt = float(item.get("alt", item.get("z", 20.0)))
            except Exception:
                continue

            try:
                heading_deg = float(item.get("heading_deg", 0.0))
            except Exception:
                heading_deg = 0.0

            yaw = math.radians(heading_deg)

            batt = 90
            try:
                batt = int(round(float(item.get("battery_pct", 90.0))))
            except Exception:
                batt = 90

            nominal = 0.0
            if speed_mps is not None:
                nominal = max(0.0, min(30.0, speed_mps))
            else:
                nominal = 10.0

            mode = str(tel.get("flight_mode", "AUTO")).strip().upper()
            if mode in {"HOLD", "PAUSED"} or str(tel.get("mission_state", "")).strip().upper() == "PAUSED":
                nominal = 0.0

            vx = nominal * math.cos(yaw)
            vy = nominal * math.sin(yaw)

            prev = self._vehicles.get(idx)
            home_sent = prev.home_sent if prev is not None else False

            out[idx] = _VehicleState(
                uav_id=uav_id,
                lat_deg=lat,
                lon_deg=lon,
                alt_m=alt,
                yaw_rad=yaw,
                vx_mps=vx,
                vy_mps=vy,
                vz_mps=0.0,
                battery_percent=_clamp_int(batt, 0, 100),
                armed=True,
                mode=mode or "AUTO",
                home_sent=home_sent,
            )

        if out:
            self._vehicles = out
            self._last_demo_tel_s = time.monotonic()
            self._warned_demo_tel_missing = False

    def _on_threat_alert(self, msg: String) -> None:
        if self._mav is None:
            return

        alert = safe_json_loads(msg.data, self.get_logger())
        if alert is None:
            return

        self._send_statustext("ATLAS threat alert received")

        if not self._auto_rtl_on_threat:
            return

        assessments = alert.get("assessments", [])
        levels = {str(a.get("threat_level", "")).upper() for a in assessments if isinstance(a, dict)}
        if {"HIGH", "MEDIUM"} & levels:
            self._publish_operator_command_rtl(target_uav="uav_1", source="ATLAS")
            self._send_statustext("Auto RTL on threat")

    def _publish_operator_command_rtl(self, *, target_uav: str, source: str) -> None:
        payload = {
            "type": "ISSUE_OVERRIDE",
            "payload": {
                "mode": "RTL",
                "target_uav": target_uav,
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
