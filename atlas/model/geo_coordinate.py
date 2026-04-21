"""Geographic coordinate representation."""

from dataclasses import dataclass


@dataclass
class GeoCoordinate:
    """WGS-84 geographic position with optional altitude."""

    latitude: float
    longitude: float
    altitude: float = 0.0

    def __str__(self) -> str:
        return f"({self.latitude:.6f}, {self.longitude:.6f}, alt={self.altitude:.1f}m)"
