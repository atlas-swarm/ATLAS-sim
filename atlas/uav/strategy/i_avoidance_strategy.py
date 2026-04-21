"""Abstract interface for collision avoidance algorithms."""

from abc import ABC, abstractmethod

from atlas.model.geo_coordinate import GeoCoordinate
from atlas.model.vector3d import Vector3D


class IAvoidanceStrategy(ABC):
    """Strategy interface that every avoidance algorithm must implement."""

    @abstractmethod
    def compute_avoidance_vector(
        self,
        current_position: GeoCoordinate,
        obstacle_position: GeoCoordinate,
        current_velocity: Vector3D,
    ) -> Vector3D:
        """Return a corrective velocity vector to avoid the given obstacle."""
        ...

    @abstractmethod
    def is_threat(
        self,
        current_position: GeoCoordinate,
        obstacle_position: GeoCoordinate,
    ) -> bool:
        """Return True if the obstacle poses a collision risk."""
        ...
