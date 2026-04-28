from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from atlas_simulation.demo_scenario import DEFAULT_MISSION_PATH, run_demo
from atlas_simulation.models import GeoCoordinate, SimConfig, Vector3D
from atlas_simulation.publisher_adapter import reset_publisher, set_publisher
from atlas_simulation.simulation_engine import (
    SUBSYSTEM_ERROR_EVENT,
    SimulationEngine,
)


class StubAgent:
    def __init__(self, uav_id: int) -> None:
        self.uav_id = uav_id
        self.position = GeoCoordinate(41.0, 29.0, 100.0)
        self.velocity = Vector3D(0.0, 0.0, 0.0)
        self.heading = 0.0
        self.battery_level = 100.0
        self.flight_mode = "PATROL"
        self.system_status = "ACTIVE"

    def update(self, delta_time_s: float) -> None:
        del delta_time_s


class FailingAgent(StubAgent):
    def update(self, delta_time_s: float) -> None:
        del delta_time_s
        raise RuntimeError("agent update failed")


class FailingPhysicsProcessor:
    def update_positions(self, **_: object) -> list[object]:
        raise RuntimeError("physics failed")


class FailingThreatDetector:
    def update(self, *_: object) -> list[object]:
        raise RuntimeError("detector failed")


class FailingTelemetryLogger:
    def __init__(self) -> None:
        self.incidents: list[dict[str, object]] = []

    def log_flight_data(self, packet: object) -> None:
        del packet
        raise RuntimeError("telemetry logger failed")

    def log_incident(
        self,
        incident_type: str,
        uav_id: int | str,
        details: str,
    ) -> None:
        self.incidents.append(
            {
                "incident_type": incident_type,
                "uav_id": uav_id,
                "details": details,
            }
        )

    def flush(self) -> None:
        return None


class FailingPublisher:
    def publish(self, message_type: str, payload: object) -> None:
        del message_type
        del payload
        raise RuntimeError("bus publish failed")


class SimulationEngineIntegrationTests(unittest.TestCase):
    def test_tick_records_subsystem_errors_without_crashing(self) -> None:
        SimulationEngine.reset_instance()
        reset_publisher()
        engine = SimulationEngine.get_instance()
        engine.initialize(SimConfig(tick_interval_ms=50))
        engine.register_uav(StubAgent(1))
        engine.register_uav(FailingAgent(2))
        engine.physics_processor = FailingPhysicsProcessor()
        engine.register_threat_detector(FailingThreatDetector(), uav_id=1)
        engine.set_data_logger(FailingTelemetryLogger())
        set_publisher(FailingPublisher())

        try:
            world_state = engine.tick()
            events = list(engine.pending_events)
        finally:
            reset_publisher()
            engine.stop()
            SimulationEngine.reset_instance()

        self.assertEqual(world_state.tick, 1)
        self.assertEqual(set(world_state.uav_states), {1, 2})
        subsystems = {
            event.details.get("subsystem")
            for event in events
            if event.event_type == SUBSYSTEM_ERROR_EVENT
        }
        self.assertIn("UAVAgent", subsystems)
        self.assertIn("PhysicsProcessor", subsystems)
        self.assertIn("ThreatDetector", subsystems)
        self.assertIn("DataLogger.telemetry", subsystems)
        self.assertIn("CommunicationBus.telemetry", subsystems)
        self.assertIn("CommunicationBus.world_state", subsystems)

    def test_mission_demo_config_matches_demo_scope(self) -> None:
        config = json.loads(DEFAULT_MISSION_PATH.read_text(encoding="utf-8"))

        self.assertEqual(config["tickIntervalMs"], 80)
        self.assertEqual(config["detectionRadius"], 170.0)
        self.assertEqual(config["formationSpacing"], 18.0)
        self.assertEqual(len(config["uavs"]), 3)
        self.assertEqual(len(config["patrol_boundary"]), 4)
        self.assertEqual(len(config["waypoints"]), 8)
        self.assertEqual(len(config["simObjects"]), 1)

    def test_mission_demo_runs_and_stays_within_tick_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = self._load_demo_config(temp_path)
            config_path = temp_path / "mission_demo.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            summary = run_demo(config_path)

        self.assertEqual(summary["mission_status"], "COMPLETED")
        self.assertEqual(summary["uav_count"], 3)
        self.assertEqual(summary["waypoint_count"], 8)
        self.assertEqual(summary["sim_object_count"], 1)
        self.assertIs(summary["event_log_contains_threat"], True)
        self.assertLess(
            summary["max_tick_duration_ms"],
            summary["tick_interval_ms"],
        )

    def test_ten_uav_demo_stays_within_tick_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config = self._load_demo_config(temp_path)
            config["mission_id"] = "mission_demo_10uav"
            config["formationSpacing"] = 8.0
            config["uavs"] = [
                {
                    "uav_id": uav_id,
                    "speed_mps": 42.0,
                }
                for uav_id in range(1, 11)
            ]
            config_path = temp_path / "mission_demo_10uav.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            summary = run_demo(config_path)

        self.assertEqual(summary["mission_status"], "COMPLETED")
        self.assertEqual(summary["uav_count"], 10)
        self.assertLess(
            summary["max_tick_duration_ms"],
            summary["tick_interval_ms"],
        )

    def _load_demo_config(self, temp_path: Path) -> dict[str, object]:
        config = json.loads(DEFAULT_MISSION_PATH.read_text(encoding="utf-8"))
        config["logs"] = {
            "flight": str(temp_path / "demo_flight_log.csv"),
            "events": str(temp_path / "demo_event_log.jsonl"),
        }
        return config


if __name__ == "__main__":
    unittest.main()
