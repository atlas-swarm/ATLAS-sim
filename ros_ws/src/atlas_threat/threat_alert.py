import uuid
from dataclasses import dataclass, field
from enum import Enum
from src.atlas.atlas_communication.telemetry_packet import GeoCoordinate


class ThreatClassification(Enum):
    UNKNOWN = "UNKNOWN"
    SUSPICIOUS_MOVEMENT = "SUSPICIOUS_MOVEMENT"
    UNAUTHORIZED_CROSSING = "UNAUTHORIZED_CROSSING"
    VEHICLE = "VEHICLE"


class SeverityLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class ThreatAlert:
    threat_coordinates: GeoCoordinate   # tehdidin konumu
    classification: ThreatClassification
    confidence_score: float
    uav_id: int
    timestamp: int
    detection_position: GeoCoordinate = None  # algılama anında UAV'ın konumu
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_acknowledged: bool = False

    def get_severity_level(self) -> SeverityLevel:
        if self.confidence_score >= 0.85:
            return SeverityLevel.HIGH
        elif self.confidence_score >= 0.60:
            return SeverityLevel.MEDIUM
        else:
            return SeverityLevel.LOW