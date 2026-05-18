"""Vision-based threat assessment combining YOLO detections and ArUco affiliation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .affiliation_scorer import (
    AFFILIATION_MODIFIERS,
    AffiliationClass,
    calculate_affiliation_score,
)
from .aruco_identifier import MarkerMatch
from .yolo_detector import Detection

TrackHistory = dict[str, list[tuple[int, int]]]

_MOBILE_TYPES = {"person", "car", "truck", "bus", "motorcycle"}


@dataclass
class ThreatAssessment:
    object_id: str
    object_type: str
    affiliation: str
    affiliation_score: float
    behavior_score: float
    final_threat_score: float
    threat_level: str
    reason: str


def _zone_centroid(polygon: list[tuple[int, int]]) -> tuple[float, float]:
    return (
        sum(p[0] for p in polygon) / len(polygon),
        sum(p[1] for p in polygon) / len(polygon),
    )


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _point_in_polygon(px: int, py: int, polygon: list[tuple[int, int]]) -> bool:
    inside = False
    prev = polygon[-1]
    for curr in polygon:
        x1, y1 = curr
        x2, y2 = prev
        if (y1 > py) != (y2 > py):
            if px < ((x2 - x1) * (py - y1) / ((y2 - y1) or 1e-12) + x1):
                inside = not inside
        prev = curr
    return inside


def _detection_centroid(detection: Detection) -> tuple[int, int]:
    x1, y1, x2, y2 = detection.bounding_box
    return (x1 + x2) // 2, (y1 + y2) // 2


def is_approaching(
    object_id: str,
    zone_polygon: list[tuple[int, int]],
    track_history: TrackHistory,
) -> bool:
    """Return True if the last tracked position is closer to the zone centroid than the previous."""
    history = track_history.get(object_id, [])
    if len(history) < 2:
        return False
    zx, zy = _zone_centroid(zone_polygon)
    px, py = history[-2]
    lx, ly = history[-1]
    return _dist(lx, ly, zx, zy) < _dist(px, py, zx, zy)


def calculate_behavior_score(
    detection: Detection,
    zone_polygon: list[tuple[int, int]],
    track_history: TrackHistory,
    object_id: str,
) -> float:
    """Accumulate behavior score from spatial and temporal signals, clamped to 1.0."""
    cx, cy = _detection_centroid(detection)
    score = 0.0

    if zone_polygon and _point_in_polygon(cx, cy, zone_polygon):
        score += 0.50

    if zone_polygon and is_approaching(object_id, zone_polygon, track_history):
        score += 0.25

    if len(track_history.get(object_id, [])) >= 3:
        score += 0.15

    if detection.object_type in _MOBILE_TYPES:
        score += 0.10

    return min(score, 1.0)


def classify_threat_level(score: float) -> str:
    """Map a final threat score to a human-readable threat level."""
    if score >= 0.75:
        return "HIGH"
    if score >= 0.50:
        return "MEDIUM"
    if score >= 0.25:
        return "LOW"
    return "NONE"


def assess_detection(
    detection: Detection,
    markers: list[MarkerMatch],
    zone_polygon: list[tuple[int, int]],
    track_history: TrackHistory,
    object_id: str,
) -> ThreatAssessment:
    """Produce a full ThreatAssessment for a single YOLO detection."""
    affiliation_class, affiliation_score = calculate_affiliation_score(detection, markers)
    behavior_score = calculate_behavior_score(detection, zone_polygon, track_history, object_id)
    modifier = AFFILIATION_MODIFIERS[affiliation_class]
    final_threat_score = behavior_score * modifier
    threat_level = classify_threat_level(final_threat_score)

    cx, cy = _detection_centroid(detection)
    reasons: list[str] = [
        f"affiliation={affiliation_class.value}(modifier={modifier:.2f})",
    ]
    if zone_polygon and _point_in_polygon(cx, cy, zone_polygon):
        reasons.append("in_zone")
    if zone_polygon and is_approaching(object_id, zone_polygon, track_history):
        reasons.append("approaching_zone")
    if len(track_history.get(object_id, [])) >= 3:
        reasons.append("tracked_3+_frames")
    if detection.object_type in _MOBILE_TYPES:
        reasons.append(f"mobile_type({detection.object_type})")

    return ThreatAssessment(
        object_id=object_id,
        object_type=detection.object_type,
        affiliation=affiliation_class.value,
        affiliation_score=affiliation_score,
        behavior_score=behavior_score,
        final_threat_score=final_threat_score,
        threat_level=threat_level,
        reason=", ".join(reasons),
    )


if __name__ == "__main__":
    det = Detection(object_type="person", confidence=0.82, bounding_box=(150, 150, 350, 450))

    zone: list[tuple[int, int]] = [(100, 100), (400, 100), (400, 500), (100, 500)]

    track: TrackHistory = {
        "obj_0": [(240, 380), (245, 360), (250, 340)],
    }

    result = assess_detection(
        detection=det,
        markers=[],
        zone_polygon=zone,
        track_history=track,
        object_id="obj_0",
    )

    print(f"object_type:        {result.object_type}")
    print(f"affiliation:        {result.affiliation}")
    print(f"behavior_score:     {result.behavior_score:.2f}")
    print(f"final_threat_score: {result.final_threat_score:.2f}")
    print(f"threat_level:       {result.threat_level}")
    print(f"reason:             {result.reason}")
