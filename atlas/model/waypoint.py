"""Mission waypoint definition."""

from dataclasses import dataclass, field

from atlas.model.geo_coordinate import GeoCoordinate


@dataclass
class Waypoint:
    """A single navigation point within a mission plan."""

    position: GeoCoordinate
    sequence: int = 0
    loiter_time: float = 0.0
    label: str = ""
    metadata: dict = field(default_factory=dict)
