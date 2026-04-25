"""
atlas_common — ortak tip ve sabit tanımları.

MessageType ve GeoCoordinate kendi paketlerinden re-export edilir.
IncidentType ve MissionStatus henüz atlas_data içinde tanımlı olmadığından
burada stub olarak tutulur; atlas_data hazır olduğunda burası güncellenir.
"""

from enum import Enum

from atlas_communication.communication_bus import MessageType
from atlas_communication.telemetry_packet import GeoCoordinate


class IncidentType(Enum):
    GEOFENCE_VIOLATION = "GEOFENCE_VIOLATION"
    MISSION_ABORT = "MISSION_ABORT"
    THREAT_DETECTED = "THREAT_DETECTED"


class MissionStatus(Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


__all__ = ["MessageType", "GeoCoordinate", "IncidentType", "MissionStatus"]
