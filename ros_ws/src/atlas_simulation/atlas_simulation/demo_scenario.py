"""Runnable 3-UAV rectangular patrol demo for the simulation core."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import time
from typing import Any

from atlas_simulation.models import (
    GeoCoordinate,
    SimConfig,
    SimEvent,
    SimObject,
    Vector3D,
    approx_distance_m,
    meters_to_longitude,
)
from atlas_simulation.simulation_engine import (
    SimulationEngine,
    THREAT_DETECTED_EVENT,
)


DEFAULT_MISSION_PATH = (
    Path(__file__).resolve().parents[1]
    / "missions"
    / "mission_demo.json"
)


class DemoDataLogger:
    """Small file logger used by the standalone demo scenario."""

    TELEMETRY_FIELDS = [
        "timestamp",
        "uav_id",
        "latitude",
        "longitude",
        "altitude",
        "velocity_x",
        "velocity_y",
        "velocity_z",
        "heading",
        "battery_level",
        "flight_mode",
        "system_status",
    ]

    def __init__(self, flight_log_path: Path, event_log_path: Path) -> None:
        self.flight_log_path = flight_log_path
        self.event_log_path = event_log_path
        self.telemetry_buffer: list[dict[str, Any]] = []
        self.event_buffer: list[dict[str, Any]] = []
        self.flight_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_flight_data(self, packet: object) -> None:
        """Collect one telemetry packet."""
        data = packet if isinstance(packet, dict) else vars(packet)
        position = data.get("position")
        velocity = data.get("velocity")
        self.telemetry_buffer.append(
            {
                "timestamp": data.get("timestamp"),
                "uav_id": data.get("uav_id"),
                "latitude": getattr(position, "latitude", None),
                "longitude": getattr(position, "longitude", None),
                "altitude": getattr(position, "altitude", None),
                "velocity_x": getattr(velocity, "x", None),
                "velocity_y": getattr(velocity, "y", None),
                "velocity_z": getattr(velocity, "z", None),
                "heading": data.get("heading"),
                "battery_level": data.get("battery_level"),
                "flight_mode": data.get("flight_mode"),
                "system_status": data.get("system_status"),
            }
        )

    def log_incident(
        self,
        incident_type: str | Any,
        uav_id: int | str,
        details: str,
    ) -> None:
        """Collect one event log record."""
        self.event_buffer.append(
            {
                "timestamp_ms": int(time.time() * 1000),
                "event_type": getattr(incident_type, "value", incident_type),
                "uav_id": uav_id,
                "details": details,
            }
        )

    def flush(self) -> None:
        """Write buffered telemetry and events to disk."""
        if self.telemetry_buffer:
            file_exists = (
                self.flight_log_path.exists()
                and self.flight_log_path.stat().st_size > 0
            )
            with self.flight_log_path.open(
                "a",
                encoding="utf-8",
                newline="",
            ) as flight_log:
                writer = csv.DictWriter(
                    flight_log,
                    fieldnames=self.TELEMETRY_FIELDS,
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerows(self.telemetry_buffer)
            self.telemetry_buffer.clear()

        if self.event_buffer:
            with self.event_log_path.open("a", encoding="utf-8") as event_log:
                for event in self.event_buffer:
                    event_log.write(json.dumps(event) + "\n")
            self.event_buffer.clear()


class DemoNavigation:
    """Minimal route tracker for demo UAV agents."""

    def __init__(self) -> None:
        self.waypoints: list[object] = []
        self.current_index = 0

    def load_route(self, waypoints: list[object]) -> None:
        """Load route and reset progress."""
        self.waypoints = list(waypoints)
        self.current_index = 0

    def current_waypoint(self) -> object | None:
        """Return the active waypoint if one remains."""
        if self.current_index < len(self.waypoints):
            return self.waypoints[self.current_index]
        return None

    def advance(self) -> bool:
        """Move to the next waypoint."""
        self.current_index += 1
        return self.current_index < len(self.waypoints)


class DemoUAVAgent:
    """Simple UAV agent that flies waypoint-to-waypoint for the demo."""

    def __init__(
        self,
        uav_id: int,
        position: GeoCoordinate,
        speed_mps: float,
    ) -> None:
        self.uav_id = uav_id
        self.position = position
        self.velocity = Vector3D(0.0, 0.0, 0.0)
        self.heading = 0.0
        self.battery_level = 100.0
        self.flight_mode = "HOVER"
        self.system_status = "ACTIVE"
        self.mission_status = "IDLE"
        self.navigation = DemoNavigation()
        self.speed_mps = speed_mps

    def update(self, delta_time_s: float) -> None:
        """Point the velocity vector toward the current waypoint."""
        del delta_time_s
        if self.mission_status != "ACTIVE":
            self.velocity = Vector3D(0.0, 0.0, 0.0)
            return

        waypoint = self.navigation.current_waypoint()
        if waypoint is None:
            self._complete()
            return

        target = waypoint.coordinate
        distance_m = approx_distance_m(self.position, target)
        if distance_m <= 3.0:
            if not self.navigation.advance():
                self._complete()
                return
            target = self.navigation.current_waypoint().coordinate

        self._aim_at(target)

    def _aim_at(self, target: GeoCoordinate) -> None:
        delta_lat_m = (target.latitude - self.position.latitude) * 111_320.0
        meters_per_lon = 111_320.0 * max(
            math.cos(math.radians(self.position.latitude)),
            1e-9,
        )
        delta_lon_m = (target.longitude - self.position.longitude) * meters_per_lon
        distance_m = max(math.hypot(delta_lon_m, delta_lat_m), 1e-9)
        scale = self.speed_mps / distance_m
        self.velocity = Vector3D(delta_lon_m * scale, delta_lat_m * scale, 0.0)
        self.heading = math.degrees(math.atan2(delta_lon_m, delta_lat_m)) % 360.0
        self.flight_mode = "PATROL"

    def _complete(self) -> None:
        self.velocity = Vector3D(0.0, 0.0, 0.0)
        self.flight_mode = "HOVER"
        self.mission_status = "COMPLETED"


class DemoThreatDetector:
    """Detects one nearby sim object and returns a simulation event."""

    def __init__(self, uav_id: int, detection_radius_m: float) -> None:
        self.uav_id = uav_id
        self.detection_radius_m = detection_radius_m
        self._seen_object_ids: set[str] = set()

    def update(
        self,
        position: GeoCoordinate,
        sim_objects: list[dict[str, object]],
    ) -> list[SimEvent]:
        """Return THREAT_DETECTED events for newly detected objects."""
        events: list[SimEvent] = []
        for sim_object in sim_objects:
            object_id = str(sim_object.get("id", "unknown"))
            if object_id in self._seen_object_ids:
                continue

            threat_position = GeoCoordinate(
                latitude=float(sim_object["lat"]),
                longitude=float(sim_object["lon"]),
                altitude=float(sim_object.get("alt", 0.0)),
            )
            if approx_distance_m(position, threat_position) > self.detection_radius_m:
                continue

            self._seen_object_ids.add(object_id)
            events.append(
                SimEvent(
                    event_type=THREAT_DETECTED_EVENT,
                    uav_id=self.uav_id,
                    details={
                        "object_id": object_id,
                        "classification": sim_object.get("type", "UNKNOWN"),
                    },
                )
            )
        return events


def run_demo(config_path: Path | str = DEFAULT_MISSION_PATH) -> dict[str, object]:
    """Run the rectangular 3-UAV patrol demo and return a summary."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    log_config = config.get("logs", {})
    flight_log_path = Path(log_config.get("flight", "logs/demo_flight_log.csv"))
    event_log_path = Path(log_config.get("events", "logs/demo_event_log.jsonl"))
    tick_interval_ms = _config_int(
        config,
        "tick_interval_ms",
        "tickIntervalMs",
        default=100,
    )
    detection_radius_m = _config_float(
        config,
        "detection_radius_m",
        "detectionRadius",
        default=180.0,
    )

    if flight_log_path.exists():
        flight_log_path.unlink()
    if event_log_path.exists():
        event_log_path.unlink()

    boundary = [
        _coordinate_from_dict(coordinate)
        for coordinate in config["patrol_boundary"]
    ]
    sim_objects = [
        SimObject(
            object_id=item["object_id"],
            position=_coordinate_from_dict(item["position"]),
            radius_m=float(item.get("radius_m", 0.0)),
            metadata=dict(item.get("metadata", {})),
        )
        for item in _config_list(config, "sim_objects", "simObjects")
    ]

    SimulationEngine.reset_instance()
    engine = SimulationEngine.get_instance()
    engine.initialize(
        SimConfig(
            patrol_boundary=boundary,
            tick_interval_ms=tick_interval_ms,
            initial_sim_objects=sim_objects,
        )
    )
    engine.set_data_logger(DemoDataLogger(flight_log_path, event_log_path))

    for index, item in enumerate(config["uavs"]):
        agent = DemoUAVAgent(
            uav_id=int(item["uav_id"]),
            position=_resolve_initial_position(config, item, index),
            speed_mps=float(item.get("speed_mps", 35.0)),
        )
        engine.register_uav(agent)
        engine.register_threat_detector(
            DemoThreatDetector(
                uav_id=agent.uav_id,
                detection_radius_m=detection_radius_m,
            ),
            uav_id=agent.uav_id,
        )

    engine.start_mission(config)
    max_ticks = _config_int(config, "max_ticks", "maxTicks", default=600)
    tick_durations_ms: list[float] = []
    for _ in range(max_ticks):
        engine.tick()
        tick_durations_ms.append(engine.last_tick_duration_ms)
        if engine._mission_status != "ACTIVE":
            break
    engine.stop()

    avg_tick_duration_ms = (
        sum(tick_durations_ms) / len(tick_durations_ms)
        if tick_durations_ms
        else 0.0
    )
    summary = {
        "mission_status": engine._mission_status,
        "ticks": engine.current_tick,
        "uav_count": len(config["uavs"]),
        "waypoint_count": len(config["waypoints"]),
        "sim_object_count": len(sim_objects),
        "tick_interval_ms": tick_interval_ms,
        "avg_tick_duration_ms": avg_tick_duration_ms,
        "max_tick_duration_ms": max(tick_durations_ms, default=0.0),
        "flight_log": str(flight_log_path),
        "event_log": str(event_log_path),
        "flight_log_exists": flight_log_path.exists(),
        "event_log_exists": event_log_path.exists(),
        "event_log_contains_threat": _file_contains(
            event_log_path,
            THREAT_DETECTED_EVENT,
        ),
    }
    if not summary["flight_log_exists"] or not summary["event_log_exists"]:
        raise RuntimeError("demo did not produce both log files")
    if not summary["event_log_contains_threat"]:
        raise RuntimeError("demo did not detect the central sim object")
    return summary


def main() -> None:
    """Console entry point."""
    summary = run_demo()
    print(json.dumps(summary, indent=2))


def _coordinate_from_dict(data: dict[str, object]) -> GeoCoordinate:
    return GeoCoordinate(
        latitude=float(data["latitude"]),
        longitude=float(data["longitude"]),
        altitude=float(data.get("altitude", 0.0)),
    )


def _resolve_initial_position(
    config: dict[str, object],
    uav_config: dict[str, object],
    index: int,
) -> GeoCoordinate:
    raw_position = _config_value(
        uav_config,
        "initial_position",
        "initialPosition",
    )
    if raw_position is not None:
        return _coordinate_from_dict(raw_position)

    raw_origin = _config_value(
        config,
        "formation_origin",
        "formationOrigin",
        default=config["waypoints"][0]["coordinate"],
    )
    origin = _coordinate_from_dict(raw_origin)
    spacing_m = _config_float(
        config,
        "formation_spacing_m",
        "formationSpacing",
        default=0.0,
    )
    return GeoCoordinate(
        latitude=origin.latitude,
        longitude=origin.longitude
        + meters_to_longitude(spacing_m * index, origin.latitude),
        altitude=origin.altitude,
    )


def _config_value(
    data: dict[str, object],
    *keys: str,
    default: object = None,
) -> object:
    for key in keys:
        if key in data:
            return data[key]
    return default


def _config_int(
    data: dict[str, object],
    *keys: str,
    default: int,
) -> int:
    return int(_config_value(data, *keys, default=default))


def _config_float(
    data: dict[str, object],
    *keys: str,
    default: float,
) -> float:
    return float(_config_value(data, *keys, default=default))


def _config_list(
    data: dict[str, object],
    *keys: str,
) -> list[dict[str, object]]:
    value = _config_value(data, *keys, default=[])
    return list(value)


def _file_contains(path: Path, text: str) -> bool:
    return path.exists() and text in path.read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
