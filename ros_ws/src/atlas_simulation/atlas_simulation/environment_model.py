"""Environment container for patrol boundaries, weather, and sim objects."""

from __future__ import annotations

from atlas_simulation.models import (
    GeoCoordinate,
    SimObject,
    WeatherState,
    approx_distance_m,
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
