import json
from dataclasses import dataclass

from atlas_common import GeoCoordinate, Vector3D, FlightMode

# UAV'ların güncel durumunu bulunduran veri paketi


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
            "position": {
                "latitude": self.position.latitude,
                "longitude": self.position.longitude,
                "altitude": self.position.altitude,
            },
            "velocity": {
                "x": self.velocity.x,
                "y": self.velocity.y,
                "z": self.velocity.z,
            },
            "battery_level": self.battery_level,
            "flight_mode": self.flight_mode.value,
            "timestamp": self.timestamp,
        })

    @staticmethod
    def from_json(data: str) -> "TelemetryPacket":
        d = json.loads(data)
        pos = d["position"]
        vel = d["velocity"]
        return TelemetryPacket(
            uav_id=d["uav_id"],
            position=GeoCoordinate(
                latitude=pos["latitude"],
                longitude=pos["longitude"],
                altitude=pos["altitude"],
            ),
            velocity=Vector3D(x=vel["x"], y=vel["y"], z=vel["z"]),
            battery_level=d["battery_level"],
            flight_mode=FlightMode(d["flight_mode"]),
            timestamp=d["timestamp"],
        )
