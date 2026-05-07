"""Lightweight executable demo runner for the integrated ATLAS backend flow."""

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
from atlas_simulation.models import WorldState
from atlas_simulation.simulation_engine import SimulationEngine
from atlas_swarm.models import UAVCommandType
from atlas_swarm.swarm_coordinator import SwarmCoordinator
from atlas_threat.threat_alert import ThreatAlert


class _DemoUAV:
    def __init__(self, uav_id: str) -> None:
        self.uav_id = uav_id
        self.received_commands = []

    def receive_command(self, cmd) -> None:
        self.received_commands.append(cmd)


def main() -> int:
    """Run the integrated ATLAS backend demo."""
    print("[ATLAS DEMO] Starting integrated backend demo...")

    bus = CommunicationBus.get_instance()
    bus.message_queue.clear()
    for listeners in bus.subscribers.values():
        listeners.clear()

    DataLogger.reset_instance()
    logger = DataLogger.get_instance(
        flight_log_path=Path("/tmp/atlas_demo_logs/flight_log.csv"),
        event_log_path=Path("/tmp/atlas_demo_logs/event_log.jsonl"),
    )

    interface = CommandCenterInterface.get_instance()
    interface.telemetry_feed.clear()
    interface.alert_display.clear_alerts()
    interface.alert_display.alert_history.clear()
    interface.last_world_state = None
    interface.is_connected = False
    interface.connect_to_engine("localhost", 9999)

    fake_uavs = [_DemoUAV("1"), _DemoUAV("2")]
    coordinator = SwarmCoordinator()
    coordinator.bind_command_bus(bus=bus, agents=fake_uavs)

    bus.publish(
        MessageType.SWARM_COMMAND,
        {
            "command": "NAVIGATE",
            "target": "ALL",
            "waypoint": None,
            "waypoint_index": 0,
        },
    )
    bus.dispatch()
    if not fake_uavs[0].received_commands or fake_uavs[0].received_commands[0].type != UAVCommandType.NAVIGATE:
        raise RuntimeError("SWARM_COMMAND did not reach UAV as UAVCommand")
    print("[OK] Swarm command reached UAV")

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
    if not interface.telemetry_feed or interface.telemetry_feed[-1] != packet:
        raise RuntimeError("Telemetry did not reach CommandCenter")
    print("[OK] Telemetry reached CommandCenter")

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
    if not interface.alert_display.alert_queue or interface.alert_display.alert_queue[-1] != alert:
        raise RuntimeError("Threat alert did not reach AlertDisplay")
    print("[OK] Threat alert reached AlertDisplay")

    world_state = WorldState(
        tick=1,
        uav_states={},
        active_alerts=[],
        timestamp_ms=123458,
    )
    SimulationEngine.get_instance()._publish_world_state_to_bus(world_state)
    if interface.last_world_state != world_state:
        raise RuntimeError("WorldState did not reach CommandCenter")
    print("[OK] WorldState reached CommandCenter")

    logger.log_flight_data(packet)
    logger.log_threat_event(alert)
    logger.flush()

    replayer = MissionReplayer()
    if not replayer.load_log(Path("/tmp/atlas_demo_logs/flight_log.csv")):
        raise RuntimeError("MissionReplayer could not load generated flight log")
    print("[OK] Logs written and replay loaded")

    print("[ATLAS DEMO] Completed successfully")
    return 0
