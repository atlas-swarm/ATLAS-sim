from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from atlas_common.enums import FormationType  # noqa: F401  (re-export)
from atlas_common.geo_coordinate import GeoCoordinate  # noqa: F401


# ------------------------------------------------------------------ #
#  UAV command (SwarmCoordinator → UAVAgent)                          #
# ------------------------------------------------------------------ #

class UAVCommandType(str, Enum):
    NAVIGATE = "NAVIGATE"
    SET_MODE = "SET_MODE"
    EMERGENCY = "EMERGENCY"


@dataclass
class UAVCommand:
    type: UAVCommandType
    payload: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ #
#  Patrol zone                                                        #
# ------------------------------------------------------------------ #

@dataclass
class PatrolZone:
    assigned_uav_id: int
    boundary: list[GeoCoordinate] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  Swarm messaging                                                    #
# ------------------------------------------------------------------ #

class SwarmMessageType(str, Enum):
    ZONE_UPDATE = "ZONE_UPDATE"
    FORMATION_CHANGE = "FORMATION_CHANGE"
    BROADCAST = "BROADCAST"


@dataclass
class SwarmMessage:
    sender_id: int
    type: SwarmMessageType
    payload: Any = None
