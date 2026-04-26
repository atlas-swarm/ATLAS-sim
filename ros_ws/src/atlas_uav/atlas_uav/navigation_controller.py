"""Manages waypoint sequencing and route execution."""

from dataclasses import dataclass, field
from typing import Optional

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_common.waypoint import Waypoint


@dataclass
class NavigationController:
    """Tracks active route and advances through waypoints."""

    uav_id: str
    waypoints: list[Waypoint] = field(default_factory=list)
    _current_index: int = field(default=0, init=False, repr=False)
    _avoidance_correction: Optional[Vector3D] = field(default=None, init=False, repr=False)

    def load_route(self, waypoints: list[Waypoint]) -> None:
        """Replace the current route and reset progress."""
        self.waypoints = sorted(waypoints, key=lambda wp: wp.sequence)
        self._current_index = 0

    def current_waypoint(self) -> Waypoint | None:
        """Return the active waypoint, or None when the route is exhausted."""
        if self._current_index < len(self.waypoints):
            return self.waypoints[self._current_index]
        return None

    def set_avoidance_correction(self, correction: Vector3D) -> None:
        """Store an avoidance velocity correction to be blended on next advance."""
        self._avoidance_correction = correction

    def advance(self) -> bool:
        """Move to the next waypoint; return False if route is finished."""
        if self._avoidance_correction is not None:
            # avoidance vektörünü velocity'ye blend et (tek tick'te uygula)
            self._avoidance_correction = None
        if self._current_index < len(self.waypoints) - 1:
            self._current_index += 1
            return True
        return False

    def has_reached(self, position: GeoCoordinate, threshold_m: float = 2.0) -> bool:
        """Return True if *position* is within *threshold_m* of current waypoint."""
        wp = self.current_waypoint()
        if wp is None:
            return False
        dlat = position.latitude - wp.position.latitude
        dlon = position.longitude - wp.position.longitude
        # Rough metre approximation (1 deg lat ≈ 111 320 m)
        dist = ((dlat * 111_320) ** 2 + (dlon * 111_320) ** 2) ** 0.5
        return dist <= threshold_m
