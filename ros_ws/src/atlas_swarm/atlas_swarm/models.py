"""Swarm-level data transfer objects and command/message enumerations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from atlas_common.geo_coordinate import GeoCoordinate


# ------------------------------------------------------------------ #
#  UAV command (atlas_uav ← atlas_swarm direction)                   #
# ------------------------------------------------------------------ #

class UAVCommandType(str, Enum):
    """Types of commands that can be dispatched to a UAVAgent."""

    NAVIGATE = "NAVIGATE"
    SET_MODE = "SET_MODE"
    EMERGENCY = "EMERGENCY"


@dataclass
class UAVCommand:
    """Command envelope sent from SwarmCoordinator to a single UAVAgent."""

    type: UAVCommandType
    payload: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ #
#  Patrol zone                                                         #
# ------------------------------------------------------------------ #

@dataclass
class PatrolZone:
    """Geographic region assigned to one UAV for surveillance."""

    assigned_uav_id: int
    boundary: list[GeoCoordinate] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  Swarm messaging                                                     #
# ------------------------------------------------------------------ #

class SwarmMessageType(str, Enum):
    """Types of messages exchanged between swarm members."""

    ZONE_UPDATE = "ZONE_UPDATE"
    FORMATION_CHANGE = "FORMATION_CHANGE"
    BROADCAST = "BROADCAST"


@dataclass
class SwarmMessage:
    """Message envelope published over CommunicationBus as SWARM_COMMAND."""

    sender_id: int
    type: SwarmMessageType
    payload: Any = None
