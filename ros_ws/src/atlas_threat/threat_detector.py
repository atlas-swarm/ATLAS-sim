import time
from src.atlas.atlas_threat.sensor_simulator import SensorSimulator
from src.atlas.atlas_threat.threat_alert import ThreatAlert, ThreatClassification
from src.atlas.atlas_communication.communication_bus import CommunicationBus, Message, MessageType
from src.atlas.atlas_communication.telemetry_packet import GeoCoordinate


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
            dist = ((obj["lat"] - position.lat) ** 2 + (obj["lon"] - position.lon) ** 2) ** 0.5 * 111000
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

    def generate_alert(self, obj: dict, position: GeoCoordinate) -> ThreatAlert:
        classification, confidence = self.classify(obj)
        alert = ThreatAlert(
            threat_coordinates=GeoCoordinate(obj["lat"], obj["lon"], 0.0),
            classification=classification,
            confidence_score=confidence,
            uav_id=self.uav_id,
            timestamp=int(time.time()),
            detection_position=position
        )
        self.bus.publish(Message(MessageType.THREAT_ALERT, alert))
        return alert

    def update(self, position: GeoCoordinate, sim_objects: list):
        detected = self.scan(position, sim_objects)
        for obj in detected:
            classification, confidence = self.classify(obj)
            if confidence >= self.detection_threshold:
                self.generate_alert(obj, position)
        self.bus.dispatch()

    def set_detection_radius(self, radius: float):
        self.detection_radius = radius