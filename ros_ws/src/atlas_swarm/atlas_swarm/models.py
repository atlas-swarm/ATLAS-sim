from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from atlas_common.enums import FormationType  # noqa: F401
from atlas_common.geo_coordinate import GeoCoordinate  # noqa: F401


@dataclass
class Waypoint:
    coordinate: GeoCoordinate
    altitude: float = 0.0
    waypoint_id: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Waypoint:
        if "coordinate" in data and isinstance(data["coordinate"], dict):
            c = data["coordinate"]
            coord = GeoCoordinate(
                latitude=c["latitude"],
                longitude=c["longitude"],
                altitude=c.get("altitude", 0.0),
            )
        elif "latitude" in data and "longitude" in data:
            coord = GeoCoordinate(
                latitude=data["latitude"],
                longitude=data["longitude"],
                altitude=data.get("altitude", 0.0),
            )
        else:
            raise ValueError(f"Cannot build GeoCoordinate from dict: {data}")
        return cls(
            coordinate=coord,
            altitude=data.get("altitude", coord.altitude),
            waypoint_id=data.get("waypoint_id", ""),
        )

    def to_dict(self) -> dict:
        return {
            "waypoint_id": self.waypoint_id,
            "coordinate": {
                "latitude": self.coordinate.latitude,
                "longitude": self.coordinate.longitude,
                "altitude": self.coordinate.altitude,
            },
            "altitude": self.altitude,
        }


class UAVCommandType(str, Enum):
    NAVIGATE  = "NAVIGATE"
    SET_MODE  = "SET_MODE"
    EMERGENCY = "EMERGENCY"
    HOVER     = "HOVER"
    CONTINUE  = "CONTINUE"
    RTL       = "RTL"


@dataclass
class UAVCommand:
    type: UAVCommandType
    payload: dict[str, Any] = field(default_factory=dict)
    target_uav_id: Optional[str] = None


@dataclass
class PatrolZone:
    assigned_uav_id: int
    boundary: list[GeoCoordinate] = field(default_factory=list)


class SwarmMessageType(str, Enum):
    ZONE_UPDATE      = "ZONE_UPDATE"
    FORMATION_CHANGE = "FORMATION_CHANGE"
    BROADCAST        = "BROADCAST"
    NAVIGATE         = "NAVIGATE"
    HOVER            = "HOVER"
    CONTINUE         = "CONTINUE"
    RTL              = "RTL"
    SET_MODE         = "SET_MODE"
    EMERGENCY        = "EMERGENCY"


@dataclass
class SwarmMessage:
    sender_id: int
    type: SwarmMessageType
    payload: Any = None
    target_uav_id: Optional[str] = None
