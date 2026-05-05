"""Self-contained data models used by the simulation core."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any


EARTH_METERS_PER_DEGREE_LAT = 111_320.0


@dataclass(slots=True)
class GeoCoordinate:
    """Geographic coordinate stored in latitude/longitude/altitude form."""

    latitude: float
    longitude: float
    altitude: float = 0.0

    def copy(self) -> "GeoCoordinate":
        """Return a detached copy of the coordinate."""
        return GeoCoordinate(self.latitude, self.longitude, self.altitude)


@dataclass(slots=True)
class Vector3D:
    """3D vector used for velocity and displacement style values."""

    x: float
    y: float
    z: float = 0.0

    def copy(self) -> "Vector3D":
        """Return a detached copy of the vector."""
        return Vector3D(self.x, self.y, self.z)


class WeatherState(str, Enum):
    """Supported weather modes for the isolated simulation core."""

    CLEAR = "CLEAR"
    FOGGY = "FOGGY"
    STORMY = "STORMY"


@dataclass(slots=True)
class SimObject:
    """A simple object placed in the simulated environment."""

    object_id: str
    position: GeoCoordinate
    radius_m: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "SimObject":
        """Return a detached copy of the object."""
        return SimObject(
            object_id=self.object_id,
            position=self.position.copy(),
            radius_m=self.radius_m,
            metadata=dict(self.metadata),
        )


@dataclass(slots=True)
class SimEvent:
    """Discrete simulation event generated during a tick."""

    event_type: str
    tick: int = 0
    timestamp_ms: int = 0
    uav_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "SimEvent":
        """Return a detached copy of the event."""
        return SimEvent(
            event_type=self.event_type,
            tick=self.tick,
            timestamp_ms=self.timestamp_ms,
            uav_id=self.uav_id,
            details=dict(self.details),
        )


@dataclass(slots=True)
class UAVState:
    """Internal simulation snapshot of one UAV."""

    uav_id: int
    position: GeoCoordinate
    velocity: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    heading: float = 0.0
    battery_level: float = 100.0
    flight_mode: str = "PATROL"
    system_status: str = "ACTIVE"
    last_valid_position: GeoCoordinate = field(
        default_factory=lambda: GeoCoordinate(0.0, 0.0, 0.0)
    )

    def copy(self) -> "UAVState":
        """Return a detached copy of the UAV state."""
        return UAVState(
            uav_id=self.uav_id,
            position=self.position.copy(),
            velocity=self.velocity.copy(),
            heading=self.heading,
            battery_level=self.battery_level,
            flight_mode=self.flight_mode,
            system_status=self.system_status,
            last_valid_position=self.last_valid_position.copy(),
        )


@dataclass(slots=True)
class WorldState:
    """Immutable-like tick snapshot published by the engine."""

    tick: int
    uav_states: dict[int, UAVState]
    active_alerts: list[object]
    timestamp_ms: int

    def copy(self) -> "WorldState":
        """Return a deep-enough copy for safe external publication."""
        return WorldState(
            tick=self.tick,
            uav_states={
                uav_id: state.copy() for uav_id, state in self.uav_states.items()
            },
            active_alerts=list(self.active_alerts),
            timestamp_ms=self.timestamp_ms,
        )


@dataclass(slots=True)
class SimConfig:
    """Configuration input used to initialize the simulation engine."""

    patrol_boundary: list[GeoCoordinate] = field(default_factory=list)
    tick_interval_ms: int = 100
    weather_state: WeatherState = WeatherState.CLEAR
    initial_sim_objects: list[SimObject] = field(default_factory=list)


def approx_distance_m(point_a: GeoCoordinate, point_b: GeoCoordinate) -> float:
    """Return an approximate metric distance between two coordinates."""
    delta_lat_m = (point_a.latitude - point_b.latitude) * EARTH_METERS_PER_DEGREE_LAT
    average_lat_rad = math.radians((point_a.latitude + point_b.latitude) / 2.0)
    meters_per_degree_lon = EARTH_METERS_PER_DEGREE_LAT * max(
        math.cos(average_lat_rad), 1e-9
    )
    delta_lon_m = (point_a.longitude - point_b.longitude) * meters_per_degree_lon
    delta_alt_m = point_a.altitude - point_b.altitude
    return math.sqrt(delta_lat_m**2 + delta_lon_m**2 + delta_alt_m**2)


def meters_to_latitude(delta_m: float) -> float:
    """Convert a north/south delta in meters to latitude delta."""
    return delta_m / EARTH_METERS_PER_DEGREE_LAT


def meters_to_longitude(delta_m: float, latitude: float) -> float:
    """Convert an east/west delta in meters to longitude delta."""
    meters_per_degree_lon = EARTH_METERS_PER_DEGREE_LAT * max(
        math.cos(math.radians(latitude)), 1e-9
    )
    return delta_m / meters_per_degree_lon


def advance_coordinate(
    coordinate: GeoCoordinate,
    velocity: Vector3D,
    delta_time_s: float,
) -> GeoCoordinate:
    """Advance a coordinate using a simple velocity-times-time calculation."""
    return GeoCoordinate(
        latitude=coordinate.latitude + meters_to_latitude(velocity.y * delta_time_s),
        longitude=coordinate.longitude
        + meters_to_longitude(velocity.x * delta_time_s, coordinate.latitude),
        altitude=coordinate.altitude + (velocity.z * delta_time_s),
    )


def is_coordinate_inside_boundary(
    coordinate: GeoCoordinate,
    boundary: list[GeoCoordinate],
) -> bool:
    """Return True when the coordinate is inside the patrol polygon."""
    if not boundary:
        return True
    if len(boundary) < 3:
        raise ValueError("boundary must contain at least 3 coordinates")

    x = coordinate.longitude
    y = coordinate.latitude
    inside = False
    previous = boundary[-1]

    for current in boundary:
        x1 = current.longitude
        y1 = current.latitude
        x2 = previous.longitude
        y2 = previous.latitude
        intersects = ((y1 > y) != (y2 > y)) and (
            x < ((x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1)
        )
        if intersects:
            inside = not inside
        previous = current

    return inside
