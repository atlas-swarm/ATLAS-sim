import json
from dataclasses import dataclass
from enum import Enum
//UAVların güncel durumunu bulunduran veri paketi

class FlightMode(Enum):
    PATROL = "PATROL"
    RTL = "RTL"
    HOVER = "HOVER"
    LAND = "LAND"
    FORMATION = "FORMATION"

@dataclass
class GeoCoordinate:
    lat: float
    lon: float
    alt: float

@dataclass
class Vector3D:
    x: float
    y: float
    z: float

@dataclass
class TelemetryPacket:
    uav_id: int
    position: GeoCoordinate
    velocity: Vector3D
    battery_level: float
    flight_mode: FlightMode
    timestamp: int

    def to_json(self) -> str:
        return json.dumps({
            "uav_id": self.uav_id,
            "position": {"lat": self.position.lat, "lon": self.position.lon, "alt": self.position.alt},
            "velocity": {"x": self.velocity.x, "y": self.velocity.y, "z": self.velocity.z},
            "battery_level": self.battery_level,
            "flight_mode": self.flight_mode.value,
            "timestamp": self.timestamp
        })

    @staticmethod
    def from_json(data: str) -> "TelemetryPacket":
        d = json.loads(data)
        return TelemetryPacket(
            uav_id=d["uav_id"],
            position=GeoCoordinate(**d["position"]),
            velocity=Vector3D(**d["velocity"]),
            battery_level=d["battery_level"],
            flight_mode=FlightMode(d["flight_mode"]),
            timestamp=d["timestamp"]
        )