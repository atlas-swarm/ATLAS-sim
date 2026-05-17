


from __future__ import annotations

import math
from enum import Enum

from aruco_identifier import MarkerMatch
from yolo_detector import Detection


class AffiliationClass(str, Enum):
    FRIENDLY_CONFIRMED = "FRIENDLY_CONFIRMED"
    FRIENDLY_PROBABLE = "FRIENDLY_PROBABLE"
    UNKNOWN = "UNKNOWN"
    UNKNOWN_EXTERNAL = "UNKNOWN_EXTERNAL"


AFFILIATION_MODIFIERS: dict[AffiliationClass, float] = {
    AffiliationClass.FRIENDLY_CONFIRMED: 0.00,
    AffiliationClass.FRIENDLY_PROBABLE: 0.35,
    AffiliationClass.UNKNOWN: 0.75,
    AffiliationClass.UNKNOWN_EXTERNAL: 1.00,
}


def _is_inside(center: tuple[int, int], box: tuple[int, int, int, int]) -> bool:
    cx, cy = center
    x1, y1, x2, y2 = box
    return x1 <= cx <= x2 and y1 <= cy <= y2


def _distance_to_box_edge(center: tuple[int, int], box: tuple[int, int, int, int]) -> float:
    cx, cy = center
    x1, y1, x2, y2 = box
    dx = max(x1 - cx, 0, cx - x2)
    dy = max(y1 - cy, 0, cy - y2)
    return math.sqrt(dx * dx + dy * dy)


def calculate_affiliation_score(
    detection: Detection,
    markers: list[MarkerMatch],
) -> tuple[AffiliationClass, float]:
    """Return affiliation class and raw score for a detection given visible markers.

    Scoring rules (in priority order):
    - Marker inside box + asset_name matches object_type → FRIENDLY_CONFIRMED, 1.0
    - Marker inside box, type mismatch                  → FRIENDLY_PROBABLE,   0.65
    - No marker in box, but one within 50 px of edge    → UNKNOWN,             0.40
    - No marker near box                                → UNKNOWN_EXTERNAL,    0.10
    """
    box = detection.bounding_box
    inside = [m for m in markers if _is_inside(m.center, box)]

    if inside:
        if any(m.asset_name == detection.object_type for m in inside):
            return AffiliationClass.FRIENDLY_CONFIRMED, 1.0
        return AffiliationClass.FRIENDLY_PROBABLE, 0.65

    if markers and any(_distance_to_box_edge(m.center, box) <= 50.0 for m in markers):
        return AffiliationClass.UNKNOWN, 0.40

    return AffiliationClass.UNKNOWN_EXTERNAL, 0.10


if __name__ == "__main__":
    det = Detection(object_type="person", confidence=0.85, bounding_box=(100, 100, 300, 400))

    marker_match = MarkerMatch(marker_id=10, center=(200, 250), asset_name="person")
    aff_class, score = calculate_affiliation_score(det, [marker_match])
    print(f"marker inside, asset_name matches  → {aff_class.value}, score={score}")

    marker_mismatch = MarkerMatch(marker_id=20, center=(200, 250), asset_name="command_vehicle")
    aff_class, score = calculate_affiliation_score(det, [marker_mismatch])
    print(f"marker inside, asset_name mismatch → {aff_class.value}, score={score}")

    aff_class, score = calculate_affiliation_score(det, [])
    print(f"no markers                          → {aff_class.value}, score={score}")
