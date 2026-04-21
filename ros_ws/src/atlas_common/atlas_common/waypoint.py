from dataclasses import dataclass

from atlas_common.geo_coordinate import GeoCoordinate


@dataclass(slots=True)
class Waypoint:
    coordinate: GeoCoordinate
    hold_time_sec: float = 0.0
    speed_mps: float = 0.0