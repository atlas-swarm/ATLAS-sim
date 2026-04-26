import time

from atlas_common import GeoCoordinate, MessageType, ThreatClassification
from atlas_communication.communication_bus import CommunicationBus
from atlas_threat.sensor_simulator import SensorSimulator
from atlas_threat.threat_alert import ThreatAlert

# Engine (simulation_engine.py) ile aynı event adı
THREAT_DETECTED_EVENT = "THREAT_DETECTED"


class ThreatDetector:
    def __init__(self, uav_id: int):
        self.uav_id = uav_id
        self.detection_radius: float = 100.0
        self.detection_threshold: float = 0.75
        self.sensor_simulator = SensorSimulator()
        self.bus = CommunicationBus.get_instance()

    def scan(self, position: GeoCoordinate, sim_objects: list) -> list:
        detected = []
        for obj in sim_objects:
            dist = (
                (obj["lat"] - position.latitude) ** 2
                + (obj["lon"] - position.longitude) ** 2
            ) ** 0.5 * 111000

            if dist <= self.detection_radius:
                detected.append(obj)

        return detected

    def classify(self, obj: dict) -> tuple:
        obj_type = obj.get("type", "UNKNOWN")

        if obj_type == "VEHICLE":
            return ThreatClassification.VEHICLE, 0.90
        elif obj_type == "PERSON":
            return ThreatClassification.SUSPICIOUS_MOVEMENT, 0.80
        elif obj_type == "CROSSING":
            return ThreatClassification.UNAUTHORIZED_CROSSING, 0.85
        else:
            return ThreatClassification.UNKNOWN, 0.50

    def generate_alert(self, obj: dict, position: GeoCoordinate, classification=None, confidence=None):
        if classification is None or confidence is None:
            classification, confidence = self.classify(obj)

        alert = ThreatAlert(
            threat_coordinates=GeoCoordinate(
                latitude=obj["lat"],
                longitude=obj["lon"],
                altitude=0.0,
            ),
            classification=classification,
            confidence_score=confidence,
            detected_by_uav_id=self.uav_id,
            timestamp=int(time.time()),
            detection_position=position,
        )

        # 📡 Bus publish (mevcut davranış korunur)
        self.bus.publish(MessageType.THREAT_ALERT, alert)

        # 🔥 Engine için event döndür
        return {
            "type": THREAT_DETECTED_EVENT,
            "details": {
                "classification": str(classification),
                "confidence": confidence,
                "object": obj,
            },
        }

    def update(self, position: GeoCoordinate, sim_objects: list):
        detected = self.scan(position, sim_objects)

        events = []

        for obj in detected:
            classification, confidence = self.classify(obj)

            if confidence >= self.detection_threshold:
                alert_event = self.generate_alert(obj, position, classification, confidence)

                # Engine bunu SimEvent'e çevirecek
                events.append(alert_event)

        self.bus.dispatch()

        return events

    def set_detection_radius(self, radius: float):
        self.detection_radius = radius