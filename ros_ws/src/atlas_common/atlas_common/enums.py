from enum import Enum


class MissionStatus(str, Enum):
    IDLE = "IDLE"
    LOADED = "LOADED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"


class FlightMode(str, Enum):
    PATROL = "PATROL"
    RTL = "RTL"
    HOVER = "HOVER"
    LAND = "LAND"
    FORMATION = "FORMATION"


class IncidentType(str, Enum):
    BATTERY_LOW = "BATTERY_LOW"
    BATTERY_CRITICAL = "BATTERY_CRITICAL"
    LINK_LOST = "LINK_LOST"
    GEOFENCE_VIOLATION = "GEOFENCE_VIOLATION"
    COLLISION_RISK = "COLLISION_RISK"
    SENSOR_FAILURE = "SENSOR_FAILURE"
    MISSION_ABORT = "MISSION_ABORT"


class ThreatClassification(str, Enum):
    UNKNOWN = "UNKNOWN"
    SUSPICIOUS_MOVEMENT = "SUSPICIOUS_MOVEMENT"
    UNAUTHORIZED_CROSSING = "UNAUTHORIZED_CROSSING"
    VEHICLE = "VEHICLE"


class SeverityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class MessageType(str, Enum):
    TELEMETRY = "TELEMETRY"
    THREAT_ALERT = "THREAT_ALERT"
    SWARM_COMMAND = "SWARM_COMMAND"
    EMERGENCY = "EMERGENCY"
    OPERATOR_COMMAND = "OPERATOR_COMMAND"
    WORLD_STATE = "WORLD_STATE"
    ZONE_UPDATE = "ZONE_UPDATE"


class FormationType(str, Enum):
    V_SHAPE = "V_SHAPE"
    GRID = "GRID"
    LINE = "LINE"
    DISTRIBUTED = "DISTRIBUTED"


class WeatherState(str, Enum):
    CLEAR = "CLEAR"
    FOGGY = "FOGGY"
    STORMY = "STORMY"
