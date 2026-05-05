"""Detects threats and delegates to the configured avoidance strategy."""

from dataclasses import dataclass

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_uav.strategy.i_avoidance_strategy import IAvoidanceStrategy


@dataclass
class CollisionAvoider:
    """Wraps an IAvoidanceStrategy and applies it when a threat is detected."""

    uav_id: str
    strategy: IAvoidanceStrategy
    safe_distance_m: float = 10.0

    def evaluate(
        self,
        position: GeoCoordinate,
        velocity: Vector3D,
        obstacles: list[GeoCoordinate],
    ) -> Vector3D | None:
        """Return a corrective vector if any obstacle is a threat, else None."""
        for obstacle in obstacles:
            if self.strategy.is_threat(position, obstacle):
                return self.strategy.compute_avoidance_vector(
                    position, obstacle, velocity
                )
        return None
