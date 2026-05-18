from __future__ import annotations

import numpy as np
import cv2

from .vision_threat_assessor import ThreatAssessment
from .yolo_detector import Detection

THREAT_COLORS: dict[str, tuple[int, int, int]] = {
    "NONE": (0, 255, 0),
    "LOW": (0, 255, 255),
    "MEDIUM": (0, 165, 255),
    "HIGH": (0, 0, 255),
}

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FALLBACK_COLOR: tuple[int, int, int] = (128, 128, 128)


def draw_detections(
    frame: np.ndarray,
    assessments: list[ThreatAssessment],
    detections: list[Detection],
) -> np.ndarray:
    out = frame.copy()
    for assessment, detection in zip(assessments, detections):
        color = THREAT_COLORS.get(assessment.threat_level, _FALLBACK_COLOR)
        x1, y1, x2, y2 = detection.bounding_box
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = f"{assessment.object_type} | {assessment.threat_level} | {assessment.final_threat_score:.2f}"
        (text_w, text_h), baseline = cv2.getTextSize(label, _FONT, 0.5, 1)
        label_y = max(y1 - 6, text_h + 4)
        cv2.rectangle(out, (x1, label_y - text_h - 4), (x1 + text_w, label_y + baseline), color, -1)
        cv2.putText(out, label, (x1, label_y - 2), _FONT, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return out


def draw_zone(
    frame: np.ndarray,
    zone_polygon: list[tuple[int, int]],
) -> np.ndarray:
    if not zone_polygon:
        return frame.copy()
    out = frame.copy()
    overlay = out.copy()
    pts = np.array(zone_polygon, dtype=np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(overlay, [pts], (0, 0, 255))
    cv2.addWeighted(overlay, 0.4, out, 0.6, 0, out)
    cv2.polylines(out, [pts], isClosed=True, color=(0, 0, 255), thickness=2)
    return out


def render_hud(
    frame: np.ndarray,
    active_threat_count: int,
    timestamp: float,
) -> np.ndarray:
    out = frame.copy()
    lines: list[tuple[str, float, int, tuple[int, int, int]]] = [
        ("ATLAS VISION", 0.7, 2, (0, 255, 0)),
        (f"Threats: {active_threat_count}", 0.5, 1, (200, 200, 200)),
        (f"T: {timestamp:.2f}s", 0.5, 1, (200, 200, 200)),
    ]
    x, y = 10, 24
    for text, scale, thickness, color in lines:
        cv2.putText(out, text, (x, y), _FONT, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
        cv2.putText(out, text, (x, y), _FONT, scale, color, thickness, cv2.LINE_AA)
        y += 22
    return out


if __name__ == "__main__":
    blank = np.zeros((480, 640, 3), dtype=np.uint8)

    dummy_detection = Detection(
        object_type="person",
        confidence=0.85,
        bounding_box=(100, 100, 200, 300),
    )
    dummy_assessment = ThreatAssessment(
        object_id="obj_0",
        object_type="person",
        affiliation="UNKNOWN_EXTERNAL",
        affiliation_score=0.10,
        behavior_score=0.75,
        final_threat_score=0.75,
        threat_level="HIGH",
        reason="affiliation=UNKNOWN_EXTERNAL(modifier=1.00), in_zone, mobile_type(person)",
    )

    result = draw_detections(blank, [dummy_assessment], [dummy_detection])
    result = render_hud(result, active_threat_count=1, timestamp=12.5)

    assert result.shape == blank.shape, f"Shape mismatch: {result.shape} != {blank.shape}"
    print(f"Output shape: {result.shape} — OK")
