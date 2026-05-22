from __future__ import annotations

"""Gazebo swarm visualizer node for the ATLAS final demo.

Purpose:
- Close the remaining demo gap where Gazebo visuals were not clearly coupled to
  the shared demo source-of-truth `/atlas/demo/telemetry`.

Approach (conservative / best-effort):
- Subscribe to `/atlas/demo/telemetry` (String JSON).
- Extract `vehicles` list (uav_id, x/y/z, heading_deg).
- Update poses for simple SDF models in Gazebo:
    demo_uav_1, demo_uav_2, demo_uav_3

Transport method:
- Prefer calling Gazebo's pose update service via the `gz service` CLI.
- If unavailable or failing, log a clear warning once and keep the demo running.

This node is intentionally NOT a physics/autopilot integration.
"""

import math
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .bridge_utils import safe_json_loads


@dataclass
class _Pose:
    x: float
    y: float
    z: float
    yaw_rad: float


class GazeboSwarmVisualizerNode(Node):
    def __init__(self) -> None:
        super().__init__("gazebo_swarm_visualizer_node")

        self.declare_parameter("telemetry_topic", "/atlas/demo/telemetry")
        self.declare_parameter("world_name", "atlas_demo_world")
        self.declare_parameter("update_rate_hz", 2.0)

        telemetry_topic = self.get_parameter("telemetry_topic").get_parameter_value().string_value
        self._world_name = self.get_parameter("world_name").get_parameter_value().string_value
        update_rate_hz = float(self.get_parameter("update_rate_hz").value)
        update_period_s = 1.0 / max(0.1, update_rate_hz)

        self._latest_poses: dict[str, _Pose] = {}
        self._last_tel_s: float | None = None

        self._gz_available: bool | None = None
        self._warned_gz_missing = False
        self._warned_pose_failed = False

        self._service_candidates = [
            f"/world/{self._world_name}/set_pose",
            f"/world/{self._world_name}/set_entity_pose",
        ]
        self._service_name: str | None = None

        self.create_subscription(String, telemetry_topic, self._on_telemetry, 10)
        self._timer = self.create_timer(update_period_s, self._on_timer)

        self.get_logger().info(
            f"Gazebo swarm visualizer ready. telemetry={telemetry_topic} world={self._world_name} rate={update_rate_hz}Hz"
        )

    def _on_telemetry(self, msg: String) -> None:
        tel = safe_json_loads(msg.data, self.get_logger())
        if tel is None:
            return

        vehicles = tel.get("vehicles")
        poses: dict[str, _Pose] = {}

        if isinstance(vehicles, list) and vehicles:
            for item in vehicles:
                if not isinstance(item, dict):
                    continue
                uav_id = str(item.get("uav_id", "")).strip()
                if not uav_id:
                    continue

                if not uav_id.startswith("uav_"):
                    continue

                try:
                    x = float(item.get("x", 0.0))
                    y = float(item.get("y", 0.0))
                    z = float(item.get("z", 1.2))
                    heading_deg = float(item.get("heading_deg", 0.0))
                except Exception:
                    continue

                poses[uav_id] = _Pose(x=x, y=y, z=z, yaw_rad=math.radians(heading_deg))
        else:
            # Backward-compatible single-vehicle payload.
            try:
                x = float(tel.get("x", 0.0))
                y = float(tel.get("y", 0.0))
                z = float(tel.get("z", 1.2))
                heading_deg = float(tel.get("heading_deg", 0.0))
            except Exception:
                return
            poses["uav_1"] = _Pose(x=x, y=y, z=z, yaw_rad=math.radians(heading_deg))

        self._latest_poses = poses
        self._last_tel_s = time.monotonic()

    def _ensure_gz_available(self) -> bool:
        if self._gz_available is not None:
            return self._gz_available

        try:
            proc = subprocess.run(
                ["gz", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            self._gz_available = proc.returncode == 0
        except Exception:
            self._gz_available = False

        if not self._gz_available and not self._warned_gz_missing:
            self.get_logger().warning(
                "Gazebo CLI 'gz' not available; demo_uav_* models will remain static"
            )
            self._warned_gz_missing = True

        return bool(self._gz_available)

    def _discover_pose_service(self) -> str | None:
        if self._service_name is not None:
            return self._service_name

        if not self._ensure_gz_available():
            return None

        for candidate in self._service_candidates:
            try:
                proc = subprocess.run(
                    ["gz", "service", "-i", "-s", candidate],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if proc.returncode == 0:
                    self._service_name = candidate
                    self.get_logger().info(f"Using Gazebo pose service: {candidate}")
                    return candidate
            except Exception:
                continue

        if not self._warned_pose_failed:
            self.get_logger().warning(
                "No supported Gazebo pose service found; demo_uav_* models will remain static"
            )
            self._warned_pose_failed = True
        return None

    def _quat_from_yaw(self, yaw_rad: float) -> tuple[float, float, float, float]:
        half = 0.5 * yaw_rad
        return (0.0, 0.0, math.sin(half), math.cos(half))

    def _set_model_pose(self, model_name: str, pose: _Pose) -> bool:
        service = self._discover_pose_service()
        if service is None:
            return False

        if not self._ensure_gz_available():
            return False

        qx, qy, qz, qw = self._quat_from_yaw(pose.yaw_rad)

        # Protobuf text request for gz.msgs.Pose
        req = (
            f'name: "{model_name}" '
            f'position {{ x: {pose.x:.4f} y: {pose.y:.4f} z: {pose.z:.4f} }} '
            f'orientation {{ x: {qx:.6f} y: {qy:.6f} z: {qz:.6f} w: {qw:.6f} }}'
        )

        try:
            proc = subprocess.run(
                [
                    "gz",
                    "service",
                    "-s",
                    service,
                    "--reqtype",
                    "gz.msgs.Pose",
                    "--reptype",
                    "gz.msgs.Boolean",
                    "--timeout",
                    "500",
                    "--req",
                    req,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return proc.returncode == 0
        except Exception:
            return False

    def _on_timer(self) -> None:
        # Don’t do anything until we have telemetry.
        if self._last_tel_s is None:
            return

        # If telemetry is stale, don’t keep hammering Gazebo.
        if (time.monotonic() - self._last_tel_s) > 2.5:
            return

        # Only drive the known demo models.
        for uav_id in ("uav_1", "uav_2", "uav_3"):
            pose = self._latest_poses.get(uav_id)
            if pose is None:
                continue

            model_name = f"demo_{uav_id}"
            ok = self._set_model_pose(model_name, pose)
            if not ok and not self._warned_pose_failed:
                # If the service call fails, warn once and keep going.
                self.get_logger().warning(
                    "Failed to update Gazebo model poses (will retry silently); camera pipeline remains intact"
                )
                self._warned_pose_failed = True


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = GazeboSwarmVisualizerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
