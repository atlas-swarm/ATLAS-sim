"""Environment container for patrol boundaries, weather, and sim objects."""

from __future__ import annotations

import math

from atlas_simulation.models import (
    EARTH_METERS_PER_DEGREE_LAT,
    GeoCoordinate,
    SimObject,
    WeatherState,
    approx_distance_m,
    is_coordinate_inside_boundary,
)


class EnvironmentModel:
    """Hold the simulated world state that the engine works against."""

    def __init__(
        self,
        patrol_boundary: list[GeoCoordinate] | None = None,
        sim_objects: list[SimObject] | None = None,
        weather_state: WeatherState = WeatherState.CLEAR,
    ) -> None:
        raw_boundary = list(patrol_boundary or [])
        if raw_boundary and len(raw_boundary) < 3:
            raise ValueError("patrol_boundary must contain at least 3 coordinates")

        self.patrol_boundary = [coordinate.copy() for coordinate in raw_boundary]
        self.weather_state = weather_state
        self.restricted_zone: list[GeoCoordinate] = []
        self.sim_objects: dict[str, SimObject] = {}
        for sim_object in sim_objects or []:
            self.add_sim_object(sim_object)

    def add_sim_object(self, sim_object: SimObject) -> None:
        """Insert or replace an object by its stable object_id."""
        self.sim_objects[sim_object.object_id] = sim_object.copy()

    def add_threat_object(self, sim_object: SimObject) -> None:
        """Add a threat object to the simulated object registry."""
        self.add_sim_object(sim_object)

    def addThreatObject(self, sim_object: SimObject) -> None:
        """Compatibility wrapper for the Week 3 camelCase integration contract."""
        self.add_threat_object(sim_object)

    def remove_sim_object(self, object_id: str) -> None:
        """Remove an object when it exists."""
        self.sim_objects.pop(object_id, None)

    def set_restricted_zone(self, polygon: list[GeoCoordinate]) -> None:
        """Set the restricted zone polygon, replacing any existing one."""
        if polygon and len(polygon) < 3:
            raise ValueError("restricted_zone polygon must contain at least 3 coordinates")
        self.restricted_zone = [coord.copy() for coord in polygon]

    def is_in_zone(self, point: GeoCoordinate) -> bool:
        """Return True if point is inside the restricted zone polygon (ray casting)."""
        if len(self.restricted_zone) < 3:
            return False
        return is_coordinate_inside_boundary(point, self.restricted_zone)

    def distance_to_zone(self, point: GeoCoordinate) -> float:
        """Return minimum distance in metres from point to the restricted zone boundary.

        Returns 0.0 when the point is inside the zone or no zone is defined.
        """
        if len(self.restricted_zone) < 3:
            return 0.0
        if self.is_in_zone(point):
            return 0.0

        avg_lat_rad = math.radians(point.latitude)
        meters_per_lon = EARTH_METERS_PER_DEGREE_LAT * math.cos(avg_lat_rad)

        def _to_local_m(coord: GeoCoordinate) -> tuple[float, float]:
            dx = (coord.longitude - point.longitude) * meters_per_lon
            dy = (coord.latitude - point.latitude) * EARTH_METERS_PER_DEGREE_LAT
            return dx, dy

        min_dist = math.inf
        n = len(self.restricted_zone)
        for i in range(n):
            ax, ay = _to_local_m(self.restricted_zone[i])
            bx, by = _to_local_m(self.restricted_zone[(i + 1) % n])
            seg_dx, seg_dy = bx - ax, by - ay
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq == 0.0:
                dist = math.sqrt(ax * ax + ay * ay)
            else:
                t = max(0.0, min(1.0, (-ax * seg_dx + -ay * seg_dy) / seg_len_sq))
                cx, cy = ax + t * seg_dx, ay + t * seg_dy
                dist = math.sqrt(cx * cx + cy * cy)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    def get_objects_in_radius(
        self,
        center: GeoCoordinate,
        radius_m: float,
    ) -> list[SimObject]:
        """Return copies of all objects overlapping the given query radius."""
        found_objects: list[SimObject] = []
        for sim_object in self.sim_objects.values():
            distance = approx_distance_m(center, sim_object.position)
            if distance <= (radius_m + sim_object.radius_m):
                found_objects.append(sim_object.copy())
        return found_objects
