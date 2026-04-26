import uuid
from dataclasses import dataclass, field
from typing import Optional

from atlas_common import GeoCoordinate, ThreatClassification, SeverityLevel


@dataclass
class ThreatAlert:
    threat_coordinates: GeoCoordinate   # tehdidin konumu
    classification: ThreatClassification
    confidence_score: float
    detected_by_uav_id: int
    timestamp: int
    detection_position: Optional[GeoCoordinate] = None  # algılama anında UAV'ın konumu
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_acknowledged: bool = False

    def get_severity_level(self) -> SeverityLevel:
        if self.confidence_score >= 0.85:
            return SeverityLevel.HIGH
        elif self.confidence_score >= 0.60:
            return SeverityLevel.MEDIUM
        else:
            return SeverityLevel.LOW
