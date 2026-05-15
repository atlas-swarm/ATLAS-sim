"""ArUco marker detection and asset identification for the ATLAS threat pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import cv2.aruco as aruco
import numpy as np

MARKER_REGISTRY: dict[int, str] = {
    10: "atlas_ugv_1",
    20: "command_vehicle",
    30: "atlas_uav_1",
}

_ARUCO_DICT = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
_ARUCO_PARAMS = aruco.DetectorParameters()
_DETECTOR = aruco.ArucoDetector(_ARUCO_DICT, _ARUCO_PARAMS)


@dataclass
class MarkerMatch:
    marker_id: int
    center: tuple[int, int]
    asset_name: str


class ArucoIdentifier:
    def detect_markers(self, frame: np.ndarray) -> list[MarkerMatch]:
        """Detect ArUco markers in frame and return registered matches with centers."""
        corners, ids, _ = _DETECTOR.detectMarkers(frame)
        if ids is None:
            return []

        matches: list[MarkerMatch] = []
        for marker_corners, marker_id in zip(corners, ids.flatten()):
            mid = int(marker_id)
            asset_name = MARKER_REGISTRY.get(mid)
            if asset_name is None:
                continue
            pts = marker_corners[0]
            cx = int(pts[:, 0].mean())
            cy = int(pts[:, 1].mean())
            matches.append(MarkerMatch(marker_id=mid, center=(cx, cy), asset_name=asset_name))
        return matches

    def is_marker_in_box(
        self,
        marker_center: tuple[int, int],
        bounding_box: tuple[int, int, int, int],
    ) -> bool:
        """Return True if marker center (cx, cy) is inside bounding box (x1, y1, x2, y2)."""
        cx, cy = marker_center
        x1, y1, x2, y2 = bounding_box
        return x1 <= cx <= x2 and y1 <= cy <= y2


if __name__ == "__main__":
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    identifier = ArucoIdentifier()
    results = identifier.detect_markers(blank_frame)
    print(f"Detections on blank frame: {results}")
