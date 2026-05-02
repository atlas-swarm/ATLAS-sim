"""Manages waypoint sequencing and route execution with smooth interpolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D

_METRES_PER_DEG: float = 111_320.0
_INTERP_ALPHA: float = 0.15


@dataclass
class NavigationController:
    """Tracks active route and advances through waypoints.

    Hafta 4 düzeltmesi (4.2.1):
    - Sert pozisyon atlamaları yerine üstel interpolasyon uygulanır.
    - avoidance_correction aktifken waypoint hedefi kaybolmaz;
      interpolasyon hedefi korunur, velocity geçici olarak blend edilir.
    """

    uav_id: str
    waypoints: list[Waypoint] = field(default_factory=list)

    _current_index: int = field(default=0, init=False, repr=False)
    _avoidance_correction: Optional[Vector3D] = field(default=None, init=False, repr=False)
    _interpolated_lat: Optional[float] = field(default=None, init=False, repr=False)
    _interpolated_lon: Optional[float] = field(default=None, init=False, repr=False)
    _interpolated_alt: Optional[float] = field(default=None, init=False, repr=False)

    def load_route(self, waypoints: list[Waypoint]) -> None:
        """Replace the current route and reset progress."""
        self.waypoints = sorted(waypoints, key=lambda wp: getattr(wp, "sequence", 0))
        self._current_index = 0
        self._avoidance_correction = None
        self._interpolated_lat = None
        self._interpolated_lon = None
        self._interpolated_alt = None

    def current_waypoint(self) -> Waypoint | None:
        """Return the active waypoint, or None when the route is exhausted."""
        if self._current_index < len(self.waypoints):
            return self.waypoints[self._current_index]
        return None

    def advance(self) -> bool:
        """Move to the next waypoint; return False if route is finished."""
        self._avoidance_correction = None
        self._interpolated_lat = None
        self._interpolated_lon = None
        self._interpolated_alt = None
        if self._current_index < len(self.waypoints) - 1:
            self._current_index += 1
            return True
        return False

    def set_avoidance_correction(self, correction: Vector3D) -> None:
        """Store an avoidance velocity correction; waypoint target is preserved."""
        self._avoidance_correction = correction

    def clear_avoidance(self) -> None:
        """Remove active avoidance correction after threat clears."""
        self._avoidance_correction = None

    def compute_velocity(
        self,
        current_position: GeoCoordinate,
        speed_mps: float = 42.0,
    ) -> Optional[Vector3D]:
        """Return a smooth velocity vector toward the current waypoint.

        avoidance_correction aktifse waypoint yönü KORUNUR; avoidance vektörü
        üzerine %80/%20 blend edilir.
        """
        wp = self.current_waypoint()
        if wp is None:
            return None

        target = wp.coordinate

        if self._interpolated_lat is None:
            self._interpolated_lat = current_position.latitude
            self._interpolated_lon = current_position.longitude
            self._interpolated_alt = current_position.altitude

        self._interpolated_lat += _INTERP_ALPHA * (target.latitude - self._interpolated_lat)
        self._interpolated_lon += _INTERP_ALPHA * (target.longitude - self._interpolated_lon)
        self._interpolated_alt += _INTERP_ALPHA * (target.altitude - self._interpolated_alt)

        dlat = self._interpolated_lat - current_position.latitude
        dlon = self._interpolated_lon - current_position.longitude
        dalt = self._interpolated_alt - current_position.altitude

        dist_m = ((dlat * _METRES_PER_DEG) ** 2 + (dlon * _METRES_PER_DEG) ** 2) ** 0.5
        if dist_m < 0.01:
            base_velocity = Vector3D(0.0, 0.0, 0.0)
        else:
            norm = dist_m / _METRES_PER_DEG
            scale = min(speed_mps / (_METRES_PER_DEG * max(norm, 1e-9)), 1.0)
            base_velocity = Vector3D(
                x=dlat * scale,
                y=dlon * scale,
                z=dalt * 0.1,
            )

        if self._avoidance_correction is not None:
            blended = Vector3D(
                x=self._avoidance_correction.x * 0.8 + base_velocity.x * 0.2,
                y=self._avoidance_correction.y * 0.8 + base_velocity.y * 0.2,
                z=self._avoidance_correction.z * 0.8 + base_velocity.z * 0.2,
            )
            self._avoidance_correction = None
            return blended

        return base_velocity

    def has_reached(self, position: GeoCoordinate, threshold_m: float = 2.0) -> bool:
        """Return True if position is within threshold_m of current waypoint."""
        wp = self.current_waypoint()
        if wp is None:
            return False
        dlat = position.latitude - wp.coordinate.latitude
        dlon = position.longitude - wp.coordinate.longitude
        dist = ((dlat * _METRES_PER_DEG) ** 2 + (dlon * _METRES_PER_DEG) ** 2) ** 0.5
        return dist <= threshold_m
