from __future__ import annotations

"""Vision bridge node for ATLAS.

This node is a feature-specific bridge under the general `atlas_ros_bridge` package.
It adapts ROS camera images into the ATLAS vision-assisted threat pipeline.

Pipeline:
- ROS Image -> OpenCV frame (cv_bridge)
- YOLO detections (evidence)
- ArUco marker matches (friendly identification evidence)
- Rule-based scoring (threat assessment)

Outputs are published as String(JSON) topics to keep integration lightweight.
"""

import math
from typing import Any

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .bridge_utils import parse_polygon_param, safe_json_dumps


def _centroid_from_bbox(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) // 2, (y1 + y2) // 2


def _distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


class _Track:
    def __init__(self, track_id: str, centroid: tuple[int, int]) -> None:
        self.track_id = track_id
        self.last_centroid = centroid


class VisionBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("vision_node")

        self.declare_parameter("camera_topic", "/camera/image_raw")
        self.declare_parameter("detections_topic", "/atlas/vision_detections")
        self.declare_parameter("alerts_topic", "/atlas/threat_alerts")
        self.declare_parameter(
            "restricted_zone_polygon",
            "[[220,140],[420,140],[420,340],[220,340]]",
        )
        self.declare_parameter("tracker_distance_px", 50)
        self.declare_parameter("tracker_max_history", 10)

        self._camera_topic = self.get_parameter("camera_topic").get_parameter_value().string_value
        self._detections_topic = (
            self.get_parameter("detections_topic").get_parameter_value().string_value
        )
        self._alerts_topic = self.get_parameter("alerts_topic").get_parameter_value().string_value

        self._detections_pub = self.create_publisher(String, self._detections_topic, 10)
        self._alerts_pub = self.create_publisher(String, self._alerts_topic, 10)
        self._sub = self.create_subscription(Image, self._camera_topic, self._on_image, 10)

        self._bridge = None
        try:
            from cv_bridge import CvBridge

            self._bridge = CvBridge()
        except Exception as exc:
            self.get_logger().error(f"cv_bridge is required to run vision_node: {exc}")

        self._yolo = None
        self._aruco = None
        self._assess_detection = None

        self._tracks: dict[str, _Track] = {}
        self._track_history: dict[str, list[tuple[int, int]]] = {}
        self._next_track_id = 1

        self._warned_missing_yolo = False
        self._warned_missing_aruco = False

        self.get_logger().info(
            f"Vision bridge ready. camera={self._camera_topic} detections={self._detections_topic} alerts={self._alerts_topic}"
        )

    def _get_zone_polygon(self) -> list[tuple[int, int]]:
        raw = self.get_parameter("restricted_zone_polygon").value
        return parse_polygon_param(raw, self.get_logger())

    def _ensure_pipeline(self) -> bool:
        if self._bridge is None:
            return False

        if self._assess_detection is None:
            try:
                from atlas_threat.vision_threat_assessor import assess_detection

                self._assess_detection = assess_detection
            except Exception as exc:
                self.get_logger().error(f"Failed to import vision assessor: {exc}")
                return False

        if self._yolo is None:
            try:
                from atlas_threat.yolo_detector import YoloDetector

                self._yolo = YoloDetector()
            except ImportError as exc:
                if not self._warned_missing_yolo:
                    self.get_logger().error(str(exc))
                    self._warned_missing_yolo = True
                return False
            except Exception as exc:
                self.get_logger().error(f"Failed to initialize YOLO detector: {exc}")
                return False

        if self._aruco is None:
            try:
                from atlas_threat.aruco_identifier import ArucoIdentifier

                self._aruco = ArucoIdentifier()
            except ImportError as exc:
                if not self._warned_missing_aruco:
                    self.get_logger().warning(str(exc))
                    self._warned_missing_aruco = True
                self._aruco = None
            except Exception as exc:
                self.get_logger().warning(f"Failed to initialize ArUco identifier: {exc}")
                self._aruco = None

        return True

    def _match_tracks(self, centroids: list[tuple[int, int]]) -> list[str]:
        """Return track_id for each centroid using nearest-neighbor matching."""
        max_dist_px = int(self.get_parameter("tracker_distance_px").value)
        max_dist_sq = max_dist_px * max_dist_px

        track_ids = list(self._tracks.keys())
        unmatched_tracks = set(track_ids)

        assigned: list[str] = []

        for centroid in centroids:
            best_track_id: str | None = None
            best_dist: int | None = None

            for track_id in list(unmatched_tracks):
                dist = _distance_sq(self._tracks[track_id].last_centroid, centroid)
                if dist > max_dist_sq:
                    continue
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_track_id = track_id

            if best_track_id is None:
                track_id = f"track_{self._next_track_id}"
                self._next_track_id += 1
                self._tracks[track_id] = _Track(track_id, centroid)
                self._track_history[track_id] = []
                assigned.append(track_id)
            else:
                unmatched_tracks.remove(best_track_id)
                self._tracks[best_track_id].last_centroid = centroid
                assigned.append(best_track_id)

        return assigned

    def _append_track_history(self, track_id: str, centroid: tuple[int, int]) -> None:
        max_len = int(self.get_parameter("tracker_max_history").value)
        history = self._track_history.setdefault(track_id, [])
        history.append(centroid)
        if len(history) > max_len:
            del history[: len(history) - max_len]

    def _on_image(self, msg: Image) -> None:
        if not self._ensure_pipeline():
            return

        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"Failed to convert Image to cv2 frame: {exc}")
            return

        try:
            detections = self._yolo.detect(frame)
        except Exception as exc:
            self.get_logger().error(f"YOLO detection failed: {exc}")
            return

        markers = []
        if self._aruco is not None:
            try:
                markers = self._aruco.detect_markers(frame)
            except Exception as exc:
                self.get_logger().warning(f"ArUco marker detection failed; continuing with no markers: {exc}")
                markers = []

        zone_polygon = self._get_zone_polygon()

        centroids = [_centroid_from_bbox(d.bounding_box) for d in detections]
        track_ids = self._match_tracks(centroids)

        assessments = []
        for detection, track_id, centroid in zip(detections, track_ids, centroids):
            self._append_track_history(track_id, centroid)
            try:
                assessment = self._assess_detection(
                    detection=detection,
                    markers=markers,
                    zone_polygon=zone_polygon,
                    track_history=self._track_history,
                    object_id=track_id,
                )
                assessments.append(assessment)
            except Exception as exc:
                self.get_logger().warning(f"Threat assessment failed for {track_id}: {exc}")

        detections_payload: dict[str, Any] = {
            "camera_topic": self._camera_topic,
            "restricted_zone_polygon": zone_polygon,
            "detections": [
                {
                    "object_type": d.object_type,
                    "confidence": d.confidence,
                    "bounding_box": list(d.bounding_box),
                }
                for d in detections
            ],
            "markers": [
                {
                    "marker_id": m.marker_id,
                    "center": list(m.center),
                    "asset_name": m.asset_name,
                }
                for m in markers
            ],
        }
        self._detections_pub.publish(String(data=safe_json_dumps(detections_payload)))

        alerts_payload: dict[str, Any] = {
            "camera_topic": self._camera_topic,
            "assessments": [
                {
                    "object_id": a.object_id,
                    "object_type": a.object_type,
                    "affiliation": a.affiliation,
                    "affiliation_score": a.affiliation_score,
                    "behavior_score": a.behavior_score,
                    "final_threat_score": a.final_threat_score,
                    "threat_level": a.threat_level,
                    "reason": a.reason,
                }
                for a in assessments
            ],
        }
        self._alerts_pub.publish(String(data=safe_json_dumps(alerts_payload)))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = VisionBridgeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
