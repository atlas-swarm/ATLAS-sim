"""Detects proximity threats and delegates to the configured avoidance strategy.

Hafta 4 düzeltmesi (4.2.2):
- safe_distance_m = 9.0 m (mission_demo.json formationSpacing=18.0 m yarısı)
- En yakın tehdit önceliklidir.
- Obstacle kümesi boşsa erken çıkış.
"""

from __future__ import annotations

from dataclasses import dataclass
from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_uav.strategy.i_avoidance_strategy import IAvoidanceStrategy

_METRES_PER_DEG: float = 111_320.0
_DEFAULT_SAFE_DISTANCE_M: float = 9.0


@dataclass
class CollisionAvoider:
    """Wraps an IAvoidanceStrategy and applies it when a threat is detected.

    Öncelik mantığı (4.2.2):
    1. Tehdit varsa → strateji compute_avoidance_vector çağırır.
    2. Dönen vektör NavigationController.set_avoidance_correction() ile iletilir.
    3. NavigationController waypoint yönüyle blend eder.
    """

    uav_id: str
    strategy: IAvoidanceStrategy
    safe_distance_m: float = _DEFAULT_SAFE_DISTANCE_M

    def evaluate(
        self,
        position: GeoCoordinate,
        velocity: Vector3D,
        obstacles: list[GeoCoordinate],
    ) -> Vector3D | None:
        """Return a corrective vector for the closest threat, else None."""
        if not obstacles:
            return None

        closest_threat: GeoCoordinate | None = None
        closest_dist_m: float = float("inf")

        for obstacle in obstacles:
            if self.strategy.is_threat(position, obstacle):
                dist_m = _approx_dist_m(position, obstacle)
                if dist_m < closest_dist_m:
                    closest_dist_m = dist_m
                    closest_threat = obstacle

        if closest_threat is None:
            return None

        return self.strategy.compute_avoidance_vector(position, closest_threat, velocity)

    def check_proximity(
        self,
        position: GeoCoordinate,
        others: list[GeoCoordinate],
    ) -> list[GeoCoordinate]:
        """Return positions within safe_distance_m (for logging/demo visibility)."""
        return [
            other for other in others
            if _approx_dist_m(position, other) <= self.safe_distance_m
        ]


def _approx_dist_m(a: GeoCoordinate, b: GeoCoordinate) -> float:
    dlat = (a.latitude - b.latitude) * _METRES_PER_DEG
    dlon = (a.longitude - b.longitude) * _METRES_PER_DEG
    return (dlat ** 2 + dlon ** 2) ** 0.5
