"""Shared enumerations for the ATLAS UAV system."""

from enum import Enum, auto


class FlightMode(Enum):
    """Operational flight modes for a UAV."""

    PATROL = auto()
    RTL = auto()
    HOVER = auto()
    LAND = auto()
    FORMATION = auto()


class MissionStatus(Enum):
    """High-level mission execution states."""

    IDLE = auto()
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    ABORTED = auto()
