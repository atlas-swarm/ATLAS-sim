"""Manages waypoint sequencing and route execution."""

from dataclasses import dataclass, field

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.waypoint import Waypoint


@dataclass
class NavigationController:
    """Tracks active route and advances through waypoints."""

    uav_id: str
    waypoints: list[Waypoint] = field(default_factory=list)
    _current_index: int = field(default=0, init=False, repr=False)

    def load_route(self, waypoints: list[Waypoint]) -> None:
        """Replace the current route and reset progress."""
        indexed_waypoints = list(enumerate(waypoints))
        self.waypoints = [
            waypoint
            for _, waypoint in sorted(
                indexed_waypoints,
                key=lambda item: self._waypoint_sort_key(item[1], item[0]),
            )
        ]
        self._current_index = 0

    def current_waypoint(self) -> Waypoint | None:
        """Return the active waypoint, or None when the route is exhausted."""
        if self._current_index < len(self.waypoints):
            return self.waypoints[self._current_index]
        return None

    def advance(self) -> bool:
        """Move to the next waypoint; return False if route is finished."""
        if self._current_index < len(self.waypoints) - 1:
            self._current_index += 1
            return True
        return False

    def has_reached(self, position: GeoCoordinate, threshold_m: float = 2.0) -> bool:
        """Return True if *position* is within *threshold_m* of current waypoint."""
        wp = self.current_waypoint()
        if wp is None:
            return False
        waypoint_position = self._waypoint_position(wp)
        dlat = position.latitude - waypoint_position.latitude
        dlon = position.longitude - waypoint_position.longitude
        # Rough metre approximation (1 deg lat ≈ 111 320 m)
        dist = ((dlat * 111_320) ** 2 + (dlon * 111_320) ** 2) ** 0.5
        return dist <= threshold_m

    @staticmethod
    def _waypoint_position(waypoint: Waypoint) -> GeoCoordinate:
        """Return waypoint position using shared or legacy field names."""
        if hasattr(waypoint, "coordinate"):
            return waypoint.coordinate
        if hasattr(waypoint, "position"):
            return waypoint.position
        raise AttributeError("Waypoint must expose either 'coordinate' or 'position'")

    @staticmethod
    def _waypoint_sort_key(waypoint: Waypoint, fallback_index: int) -> tuple[int, int | str]:
        """Sort by waypoint_id when numeric, else sequence, else preserve input order."""
        waypoint_id = getattr(waypoint, "waypoint_id", None)
        if waypoint_id not in (None, ""):
            try:
                return (0, int(waypoint_id))
            except (TypeError, ValueError):
                return (1, str(waypoint_id))

        if hasattr(waypoint, "sequence"):
            return (2, getattr(waypoint, "sequence"))

        return (3, fallback_index)
