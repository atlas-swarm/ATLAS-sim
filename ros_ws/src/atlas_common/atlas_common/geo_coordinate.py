from dataclasses import dataclass


@dataclass(slots=True)
class GeoCoordinate:
    latitude: float
    longitude: float
    altitude: float = 0.0