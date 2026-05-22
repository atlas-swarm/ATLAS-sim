from __future__ import annotations

"""ATLAS final demo structured data logger.

LLD alignment goals:
- Persist telemetry, threat alerts, operator/runtime commands as JSONL.
- Telemetry records follow the TelemetryPacket semantics described in the LLD.

This is a demo/bridge-layer component (ROS adapter layer), intentionally kept
lightweight and resilient:
- Invalid JSON never crashes the node.
- Log directory is created if missing.
- Writes are line-buffered and flushed.
"""

import csv
import os
import time
from dataclasses import dataclass
from typing import Any

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .bridge_utils import safe_json_dumps, safe_json_loads


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uav_id_to_int(uav_id: str) -> int:
    try:
        if uav_id.startswith("uav_"):
            return int(uav_id.split("_")[-1])
    except Exception:
        pass
    return 0


def _system_status_from(tel: dict[str, Any]) -> str:
    mission_state = str(tel.get("mission_state", "")).upper()
    flight_mode = str(tel.get("flight_mode", "")).upper()

    if mission_state == "PAUSED" or flight_mode == "HOLD":
        return "HOLD"
    if mission_state == "RETURNING_TO_BASE" or flight_mode == "RTL":
        return "RETURNING"
    return "ACTIVE"


@dataclass
class _Files:
    telemetry_jsonl: str
    threat_jsonl: str
    command_jsonl: str
    incident_jsonl: str
    telemetry_csv: str


class DemoDataLoggerNode(Node):
    def __init__(self) -> None:
        super().__init__("demo_data_logger_node")

        self.declare_parameter("log_dir", "/ros_ws/log/atlas_demo")
        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter("operator_commands_topic", "/atlas/operator_commands")
        self.declare_parameter("runtime_commands_topic", "/atlas/demo/runtime_commands")
        self.declare_parameter("vision_detections_topic", "/atlas/vision_detections")
        self.declare_parameter("camera_topic", "/camera/image_raw")

        self._log_dir = self.get_parameter("log_dir").get_parameter_value().string_value

        self._files = _Files(
            telemetry_jsonl=os.path.join(self._log_dir, "telemetry_log.jsonl"),
            threat_jsonl=os.path.join(self._log_dir, "threat_log.jsonl"),
            command_jsonl=os.path.join(self._log_dir, "command_log.jsonl"),
            incident_jsonl=os.path.join(self._log_dir, "incident_log.jsonl"),
            telemetry_csv=os.path.join(self._log_dir, "telemetry_log.csv"),
        )

        os.makedirs(self._log_dir, exist_ok=True)

        self._telemetry_fp = open(self._files.telemetry_jsonl, "a", encoding="utf-8", buffering=1)
        self._threat_fp = open(self._files.threat_jsonl, "a", encoding="utf-8", buffering=1)
        self._command_fp = open(self._files.command_jsonl, "a", encoding="utf-8", buffering=1)
        self._incident_fp = open(self._files.incident_jsonl, "a", encoding="utf-8", buffering=1)

        self._csv_fp = open(self._files.telemetry_csv, "a", encoding="utf-8", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_fp,
            fieldnames=[
                "timestamp",
                "uavId",
                "lat",
                "lon",
                "alt",
                "vx",
                "vy",
                "vz",
                "heading",
                "batteryLevel",
                "flightMode",
                "systemStatus",
            ],
        )
        if self._csv_fp.tell() == 0:
            self._csv_writer.writeheader()
            self._csv_fp.flush()

        self.create_subscription(
            String,
            self.get_parameter("telemetry_topic").get_parameter_value().string_value,
            self._on_telemetry,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("alerts_topic").get_parameter_value().string_value,
            self._on_threat,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("operator_commands_topic").get_parameter_value().string_value,
            self._on_operator_command,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("runtime_commands_topic").get_parameter_value().string_value,
            self._on_runtime_command,
            50,
        )
        self.create_subscription(
            String,
            self.get_parameter("vision_detections_topic").get_parameter_value().string_value,
            self._on_vision_detections,
            10,
        )
        self.create_subscription(
            Image,
            self.get_parameter("camera_topic").get_parameter_value().string_value,
            self._on_camera,
            10,
        )

        self._last_detector_incident_s: float | None = None
        self._last_camera_frame_s: float | None = None
        self._last_camera_incident_s: float | None = None
        self._last_vision_msg_s: float | None = None
        self._last_vision_incident_s: float | None = None

        self._health_timer = self.create_timer(5.0, self._on_health_timer)

        self.get_logger().info(
            "Demo data logger ready. logs at "
            + self._log_dir
            + " (telemetry_log.jsonl, threat_log.jsonl, command_log.jsonl, incident_log.jsonl)"
        )

    def _write_jsonl(self, fp, payload: dict[str, Any]) -> None:
        fp.write(safe_json_dumps(payload) + "\n")

    def _log_incident(self, category: str, message: str, extra: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "Incident",
            "timestamp": _now_ms(),
            "category": category,
            "message": message,
        }
        if extra:
            payload["extra"] = extra
        self._write_jsonl(self._incident_fp, payload)

    def _on_telemetry(self, msg: String) -> None:
        tel = safe_json_loads(msg.data, self.get_logger())
        if tel is None:
            self._log_incident("telemetry_parse_failed", "Invalid telemetry JSON")
            return

        vehicles = tel.get("vehicles")
        if not isinstance(vehicles, list) or not vehicles:
            vehicles = [tel]

        for item in vehicles:
            if not isinstance(item, dict):
                continue

            uav_id = str(item.get("uav_id", tel.get("uav_id", "uav_1")))
            uav_int = _uav_id_to_int(uav_id)

            lat = float(item.get("lat", 0.0))
            lon = float(item.get("lon", 0.0))
            alt = float(item.get("alt", item.get("z", 0.0)))

            vx = float(item.get("vx", 0.0))
            vy = float(item.get("vy", 0.0))
            vz = float(item.get("vz", 0.0))

            heading = float(item.get("heading_deg", 0.0))
            battery_pct = float(item.get("battery_pct", 0.0))

            flight_mode = str(item.get("flight_mode", tel.get("flight_mode", "AUTO")))
            system_status = _system_status_from({
                "mission_state": item.get("mission_state", tel.get("mission_state")),
                "flight_mode": flight_mode,
            })

            packet = {
                "type": "TelemetryPacket",
                "uavId": uav_int,
                "timestamp": int(tel.get("timestamp_ms", _now_ms())),
                "position": {"lat": lat, "lon": lon, "alt": alt},
                "velocity": {"x": vx, "y": vy, "z": vz},
                "heading": heading,
                "batteryLevel": max(0.0, min(battery_pct / 100.0, 1.0)),
                "flightMode": flight_mode,
                "systemStatus": system_status,
            }
            self._write_jsonl(self._telemetry_fp, packet)

            self._csv_writer.writerow(
                {
                    "timestamp": packet["timestamp"],
                    "uavId": uav_int,
                    "lat": lat,
                    "lon": lon,
                    "alt": alt,
                    "vx": vx,
                    "vy": vy,
                    "vz": vz,
                    "heading": heading,
                    "batteryLevel": packet["batteryLevel"],
                    "flightMode": flight_mode,
                    "systemStatus": system_status,
                }
            )
        self._csv_fp.flush()

    def _on_threat(self, msg: String) -> None:
        alert = safe_json_loads(msg.data, self.get_logger())
        if alert is None:
            self._log_incident("threat_parse_failed", "Invalid threat JSON")
            return

        payload: dict[str, Any] = {
            "type": "ThreatAlert",
            "timestamp": int(alert.get("timestamp_ms", _now_ms())),
            "source": str(alert.get("source", "unknown")),
            "assessments": alert.get("assessments", []),
            "recommendedAction": alert.get("recommendedAction", "OPERATOR_REVIEW"),
        }
        self._write_jsonl(self._threat_fp, payload)

    def _log_command(self, source: str, command: str, payload: dict[str, Any]) -> None:
        entry = {
            "type": "OperatorCommand",
            "timestamp": _now_ms(),
            "source": source,
            "command": command,
            "payload": payload,
        }
        self._write_jsonl(self._command_fp, entry)

    def _on_operator_command(self, msg: String) -> None:
        cmd = safe_json_loads(msg.data, self.get_logger())
        if cmd is None:
            self._log_incident("operator_command_parse_failed", "Invalid operator command JSON")
            return
        self._log_command("manual_ros", str(cmd.get("type", "")), cmd)

    def _on_runtime_command(self, msg: String) -> None:
        cmd = safe_json_loads(msg.data, self.get_logger())
        if cmd is None:
            self._log_incident("runtime_command_parse_failed", "Invalid runtime command JSON")
            return
        self._log_command("runtime_command", str(cmd.get("command", "")), cmd)

    def _on_vision_detections(self, msg: String) -> None:
        detections = safe_json_loads(msg.data, self.get_logger())
        self._last_vision_msg_s = time.monotonic()
        if detections is None:
            return

        det_count = detections.get("detection_count")
        if det_count is None:
            return

        if isinstance(det_count, int) and det_count < 0:
            self._log_incident("vision_invalid_detection_count", "Vision detection_count invalid")

    def _on_camera(self, msg: Image) -> None:
        _ = msg
        self._last_camera_frame_s = time.monotonic()

    def _on_health_timer(self) -> None:
        now_s = time.monotonic()

        # Camera should be producing frames when Gazebo+bridge are healthy.
        if self._last_camera_frame_s is None or (now_s - self._last_camera_frame_s) > 5.0:
            if self._last_camera_incident_s is None or (now_s - self._last_camera_incident_s) > 30.0:
                self._log_incident(
                    "camera_inactive",
                    "No /camera/image_raw frames received recently",
                )
                self._last_camera_incident_s = now_s

        # Vision node best-effort; if it never publishes, record an incident (once per minute).
        if self._last_vision_msg_s is None or (now_s - self._last_vision_msg_s) > 10.0:
            if self._last_vision_incident_s is None or (now_s - self._last_vision_incident_s) > 60.0:
                self._log_incident(
                    "vision_inactive",
                    "No /atlas/vision_detections messages received recently (YOLO may be unavailable)",
                )
                self._last_vision_incident_s = now_s

    def destroy_node(self) -> bool:
        try:
            self._telemetry_fp.close()
            self._threat_fp.close()
            self._command_fp.close()
            self._incident_fp.close()
            self._csv_fp.close()
        except Exception:
            pass
        return super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = DemoDataLoggerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
