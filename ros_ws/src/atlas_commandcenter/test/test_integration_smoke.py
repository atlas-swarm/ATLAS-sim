"""Smoke tests for command center, communication, and data flow."""

from pathlib import Path

from atlas_commandcenter import CommandCenterInterface
from atlas_common import (
    FlightMode,
    GeoCoordinate,
    MessageType,
    ThreatClassification,
    Vector3D,
)
from atlas_communication import CommunicationBus, TelemetryPacket
from atlas_data import DataLogger, MissionReplayer
from atlas_threat.threat_alert import ThreatAlert


def test_commandcenter_datalogger_smoke(tmp_path: Path) -> None:
    """Validate telemetry, alert, logging, and replay integration."""
    bus = CommunicationBus.get_instance()
    bus.message_queue.clear()
    for listeners in bus.subscribers.values():
        listeners.clear()

    DataLogger.reset_instance()
    logger = DataLogger.get_instance(
        flight_log_path=tmp_path / "flight_log.csv",
        event_log_path=tmp_path / "event_log.jsonl",
    )

    interface = CommandCenterInterface.get_instance()
    interface.telemetry_feed.clear()
    interface.alert_display.clear_alerts()
    interface.alert_display.alert_history.clear()
    interface.is_connected = False
    interface.connect_to_engine("localhost", 9999)

    packet = TelemetryPacket(
        uav_id=1,
        position=GeoCoordinate(latitude=39.0, longitude=32.0, altitude=120.0),
        velocity=Vector3D(x=1.0, y=2.0, z=0.0),
        battery_level=0.75,
        flight_mode=FlightMode.PATROL,
        timestamp=123456,
    )

    bus.publish(MessageType.TELEMETRY, packet)
    bus.dispatch()

    assert interface.telemetry_feed[-1] == packet
    logger.log_flight_data(packet)

    alert = ThreatAlert(
        threat_coordinates=GeoCoordinate(latitude=39.1, longitude=32.1, altitude=0.0),
        classification=ThreatClassification.VEHICLE,
        confidence_score=0.9,
        detected_by_uav_id=1,
        timestamp=123457,
        detection_position=GeoCoordinate(latitude=39.0, longitude=32.0, altitude=120.0),
    )

    bus.publish(MessageType.THREAT_ALERT, alert)
    bus.dispatch()

    assert interface.alert_display.alert_queue[-1] == alert
    logger.log_threat_event(alert)

    logger.flush()

    replayer = MissionReplayer()
    assert replayer.load_log(tmp_path / "flight_log.csv") is True
    assert replayer.loaded_frames
