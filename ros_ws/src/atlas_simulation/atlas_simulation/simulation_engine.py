"""Simulation engine singleton and tick lifecycle implementation."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import threading
import time

from atlas_simulation.environment_model import EnvironmentModel
from atlas_simulation.models import (
    GeoCoordinate,
    SimConfig,
    SimEvent,
    UAVState,
    Vector3D,
    WorldState,
)
from atlas_simulation.physics_processor import PhysicsProcessor
from atlas_simulation.publisher_adapter import (
    dispatch_messages,
    publish_emergency_event,
    publish_telemetry,
    publish_world_state,
)


MISSION_START_EVENT = "MISSION_START"
MISSION_COMPLETE_EVENT = "MISSION_COMPLETE"
MISSION_ABORT_EVENT = "MISSION_ABORT"
EMERGENCY_EVENT = "EMERGENCY_EVENT"
GEOFENCE_VIOLATION_EVENT = "GEOFENCE_VIOLATION"
SUBSYSTEM_ERROR_EVENT = "SUBSYSTEM_ERROR"
THREAT_DETECTED_EVENT = "THREAT_DETECTED"


def _enum_or_value(value: object, default: str) -> str:
    """Return enum value strings while preserving plain strings."""
    if value is None:
        return default
    return str(getattr(value, "value", value))


@dataclass
class _LoopState:
    """Private runtime state for the background loop thread."""

    stop_event: threading.Event
    thread: threading.Thread | None = None


@dataclass(slots=True)
class _MissionWaypoint:
    """Waypoint adapter compatible with current and branch navigation code."""

    coordinate: GeoCoordinate
    sequence: int = 0
    waypoint_id: str | None = None
    hold_time_sec: float = 0.0
    speed_mps: float = 0.0

    @property
    def position(self) -> GeoCoordinate:
        """Return coordinate through the name used by NavigationController."""
        return self.coordinate


class SimulationEngine:
    """Singleton engine responsible for deterministic tick execution."""

    _instance: "SimulationEngine | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self.current_tick = 0
        self.tick_interval_ms = 100
        self.is_running = False
        self.is_paused = False
        self.uav_registry: dict[int, object] = {}
        self.environment = EnvironmentModel()
        self.physics_processor = PhysicsProcessor()
        self.pending_events: list[SimEvent] = []
        self.active_alerts: list[object] = []
        self._last_world_state: WorldState | None = None
        self._data_logger: object | None = None
        self._data_logger_available = True
        self._active_mission: object | None = None
        self._mission_status = "IDLE"
        self._mission_waypoints: list[_MissionWaypoint] = []
        self._threat_detectors: dict[int, object] = {}

        self._initialized = False
        self._lock = threading.RLock()
        self._loop_state = _LoopState(stop_event=threading.Event())

    @property
    def last_world_state(self) -> WorldState | None:
        """Return a detached copy of the latest completed world snapshot."""
        with self._lock:
            if self._last_world_state is None:
                return None
            return self._last_world_state.copy()

    @classmethod
    def get_instance(cls) -> "SimulationEngine":
        """Return the singleton engine instance."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance for isolated tests."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.stop()
            cls._instance = None

    def initialize(self, config: SimConfig) -> None:
        """Initialize runtime state from a config object."""
        self.stop()

        with self._lock:
            if self._loop_state.thread and self._loop_state.thread.is_alive():
                raise RuntimeError(
                    "SimulationEngine loop is still stopping; "
                    "initialize cannot continue"
                )
            self.current_tick = 0
            self.tick_interval_ms = max(1, config.tick_interval_ms)
            self.is_running = False
            self.is_paused = False
            self.uav_registry = {}
            self.environment = EnvironmentModel(
                patrol_boundary=config.patrol_boundary,
                sim_objects=config.initial_sim_objects,
                weather_state=config.weather_state,
            )
            self.physics_processor = PhysicsProcessor()
            self.pending_events = []
            self.active_alerts = []
            self._last_world_state = None
            self._data_logger = None
            self._data_logger_available = True
            self._active_mission = None
            self._mission_status = "IDLE"
            self._mission_waypoints = []
            self._threat_detectors = {}
            self._loop_state.stop_event = threading.Event()
            self._initialized = True

    def register_uav(self, agent: object) -> None:
        """Register any agent exposing a compatible uav_id and state fields."""
        if not self._initialized:
            raise RuntimeError(
                "SimulationEngine must be initialized before registering UAVs"
            )

        uav_id = self._normalize_uav_id(agent)
        with self._lock:
            self.uav_registry[uav_id] = agent

    def register_threat_detector(
        self,
        detector: object,
        uav_id: int | str | None = None,
    ) -> None:
        """Register a ThreatDetector-like object to run after UAV updates."""
        resolved_uav_id = (
            self._normalize_uav_id(detector)
            if uav_id is None and hasattr(detector, "uav_id")
            else int(uav_id if uav_id is not None else len(self._threat_detectors))
        )
        with self._lock:
            self._threat_detectors[resolved_uav_id] = detector

    def registerThreatDetector(
        self,
        detector: object,
        uav_id: int | str | None = None,
    ) -> None:
        """Compatibility wrapper for camelCase integration contracts."""
        self.register_threat_detector(detector, uav_id)

    def set_data_logger(self, logger: object | None) -> None:
        """Inject a logger instance for demos or tests."""
        with self._lock:
            self._data_logger = logger
            self._data_logger_available = logger is not None

    def start_mission(self, mission_plan: object) -> None:
        """Start a mission and load its waypoints into registered UAV agents."""
        if not self._initialized:
            raise RuntimeError("SimulationEngine must be initialized before missions")

        waypoints = self._extract_waypoints(mission_plan)
        if not waypoints:
            raise ValueError("mission_plan must contain at least one waypoint")

        boundary = self._extract_patrol_boundary(mission_plan)
        mission_id = self._read_value(mission_plan, "mission_id", "mission")

        with self._lock:
            self._active_mission = mission_plan
            self._mission_status = "ACTIVE"
            self._mission_waypoints = waypoints
            if boundary:
                self.environment.patrol_boundary = [
                    coordinate.copy() for coordinate in boundary
                ]

            for agent in self.uav_registry.values():
                self._load_agent_route(agent, waypoints)

        self._record_and_log_event(
            SimEvent(
                event_type=MISSION_START_EVENT,
                details={
                    "mission_id": mission_id,
                    "waypoint_count": len(waypoints),
                    "uav_count": len(self.uav_registry),
                },
            )
        )

    def startMission(self, mission_plan: object) -> None:
        """Compatibility wrapper for camelCase MissionController integrations."""
        self.start_mission(mission_plan)

    def complete_mission(self, reason: str = "all waypoints completed") -> None:
        """Complete the active mission, stop the engine, and flush logs."""
        with self._lock:
            if self._mission_status == "COMPLETED":
                return
            self._mission_status = "COMPLETED"

        self._record_and_log_event(
            SimEvent(
                event_type=MISSION_COMPLETE_EVENT,
                details={"reason": reason},
            )
        )
        self.stop()

    def abort_mission(self, reason: str = "mission aborted") -> None:
        """Abort the active mission, command RTL, stop, and flush logs."""
        with self._lock:
            if self._mission_status == "ABORTED":
                return
            self._mission_status = "ABORTED"
            agents = list(self.uav_registry.values())

        for agent in agents:
            self._set_agent_mode(agent, "RTL")

        self._record_and_log_event(
            SimEvent(
                event_type=MISSION_ABORT_EVENT,
                details={"reason": reason, "uav_count": len(agents)},
            )
        )
        self.stop()

    def abortMission(self, reason: str = "mission aborted") -> None:
        """Compatibility wrapper for camelCase integrations."""
        self.abort_mission(reason)

    def trigger_rtl(self, agent: object, reason: str) -> SimEvent:
        """Move a UAV into RTL mode and emit an emergency event."""
        uav_id = self._normalize_uav_id(agent)
        self._set_agent_mode(agent, "RTL")

        emergency = getattr(agent, "emergency", None)
        report_fault = getattr(emergency, "report_fault", None)
        if callable(report_fault):
            report_fault(reason)

        event = SimEvent(
            event_type=EMERGENCY_EVENT,
            uav_id=uav_id,
            details={"reason": reason, "action": "RTL"},
        )
        self._record_and_log_event(event)
        self._safe_publish_emergency_event(event)
        return event

    def triggerRTL(self, agent: object, reason: str) -> SimEvent:
        """Compatibility wrapper for EmergencyHandler.triggerRTL flows."""
        return self.trigger_rtl(agent, reason)

    def start(self) -> None:
        """Start or resume the background simulation loop."""
        if not self._initialized:
            raise RuntimeError("SimulationEngine must be initialized before start")

        with self._lock:
            thread = self._loop_state.thread
            if thread is not None and thread.is_alive():
                if self._loop_state.stop_event.is_set() and not self.is_running:
                    raise RuntimeError(
                        "SimulationEngine loop is still stopping; cannot start yet"
                    )
                self.is_running = True
                self.is_paused = False
                return
            if thread is not None and not thread.is_alive():
                self._loop_state.thread = None

            self._loop_state.stop_event = threading.Event()
            self.is_running = True
            self.is_paused = False
            self._loop_state.thread = threading.Thread(
                target=self._run_loop,
                name="SimulationEngineLoop",
                daemon=True,
            )
            self._loop_state.thread.start()

    def pause(self) -> None:
        """Pause tick advancement without resetting state."""
        with self._lock:
            if self.is_running:
                self.is_paused = True

    def stop(self) -> None:
        """Stop the background loop and clear live thread state."""
        with self._lock:
            self.is_running = False
            self.is_paused = False
            self._loop_state.stop_event.set()
            thread = self._loop_state.thread

        if (
            thread
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(1.0, self.tick_interval_ms / 1000.0 * 2))

        with self._lock:
            if thread is None or not thread.is_alive():
                self._loop_state.thread = None

        self._flush_data_logger()

    def run_cycle(self) -> WorldState:
        """Execute one complete simulation tick and publish the snapshot."""
        if not self._initialized:
            raise RuntimeError(
                "SimulationEngine must be initialized before running cycles"
            )

        with self._lock:
            self.pending_events.clear()
            self.current_tick += 1
            timestamp_ms = int(time.time() * 1000)
            delta_time_s = self.tick_interval_ms / 1000.0

            self._update_registered_agents(delta_time_s)
            uav_states = self._collect_uav_states()
            try:
                new_events = self.physics_processor.update_positions(
                    uav_states=uav_states,
                    delta_time_s=delta_time_s,
                    environment=self.environment,
                )
            except Exception as exc:
                new_events = [
                    self._build_error_event("PhysicsProcessor", exc)
                ]
            self._handle_physics_events(new_events)
            self._stamp_events(new_events, timestamp_ms)
            self.pending_events.extend(new_events)
            self._sync_uav_states(uav_states)
            threat_events = self._update_threat_detectors(uav_states)
            self._stamp_events(threat_events, timestamp_ms)
            self.pending_events.extend(threat_events)
            telemetry_packets = [
                self._build_telemetry_packet(state, timestamp_ms)
                for state in uav_states.values()
            ]
            should_flush_logger = self.current_tick % 10 == 0
            should_complete_mission = self._should_complete_mission()
            events_to_log = [event.copy() for event in self.pending_events]

            world_state = WorldState(
                tick=self.current_tick,
                uav_states={
                    uav_id: state.copy() for uav_id, state in uav_states.items()
                },
                active_alerts=list(self.active_alerts),
                timestamp_ms=timestamp_ms,
            )
            self._last_world_state = world_state.copy()
            published_world_state = world_state.copy()
            returned_world_state = world_state.copy()

        for packet in telemetry_packets:
            self._safe_publish_telemetry(packet)
        self._log_telemetry_packets(telemetry_packets, should_flush=False)
        self._log_events(events_to_log)
        self._safe_publish_world_state(published_world_state)
        self._safe_dispatch_messages()
        if should_flush_logger:
            self._flush_data_logger()
        if should_complete_mission:
            self.complete_mission()
        return returned_world_state

    def tick(self) -> WorldState:
        """Execute one simulation tick; compatibility alias for run_cycle()."""
        return self.run_cycle()

    def _run_loop(self) -> None:
        """Run the background tick loop until stop is requested."""
        while not self._loop_state.stop_event.is_set():
            with self._lock:
                paused = self.is_paused

            if paused:
                time.sleep(0.01)
                continue

            start_time = time.monotonic()
            try:
                self.run_cycle()
            except Exception as exc:  # pragma: no cover - defensive loop path
                self._record_and_log_event(
                    self._build_error_event("SimulationEngine", exc)
                )

            elapsed = time.monotonic() - start_time
            sleep_s = max(0.0, self.tick_interval_ms / 1000.0 - elapsed)
            if sleep_s > 0:
                self._loop_state.stop_event.wait(timeout=sleep_s)

    def _extract_waypoints(self, mission_plan: object) -> list[_MissionWaypoint]:
        """Normalize mission-plan waypoints into a route shape agents can load."""
        raw_waypoints = self._read_value(mission_plan, "waypoints", [])
        waypoints: list[_MissionWaypoint] = []
        for index, raw_waypoint in enumerate(raw_waypoints or []):
            raw_coordinate = self._read_value(
                raw_waypoint,
                "coordinate",
                self._read_value(raw_waypoint, "position", raw_waypoint),
            )
            waypoints.append(
                _MissionWaypoint(
                    coordinate=self._read_coordinate(raw_coordinate),
                    sequence=int(self._read_value(raw_waypoint, "sequence", index)),
                    waypoint_id=self._read_value(
                        raw_waypoint,
                        "waypoint_id",
                        self._read_value(raw_waypoint, "id", None),
                    ),
                    hold_time_sec=float(
                        self._read_value(raw_waypoint, "hold_time_sec", 0.0)
                    ),
                    speed_mps=float(
                        self._read_value(raw_waypoint, "speed_mps", 0.0)
                    ),
                )
            )
        return waypoints

    def _extract_patrol_boundary(self, mission_plan: object) -> list[GeoCoordinate]:
        """Normalize an optional mission patrol boundary."""
        raw_boundary = self._read_value(mission_plan, "patrol_boundary", [])
        return [self._read_coordinate(coordinate) for coordinate in raw_boundary or []]

    def _load_agent_route(
        self,
        agent: object,
        waypoints: list[_MissionWaypoint],
    ) -> None:
        """Load a mission route into a UAVAgent-like object."""
        navigation = getattr(agent, "navigation", None)
        load_route = getattr(navigation, "load_route", None)
        if callable(load_route):
            load_route(list(waypoints))

        first_waypoint = waypoints[0]
        for method_name in ("navigate_to", "set_waypoint", "set_target_waypoint"):
            method = getattr(agent, method_name, None)
            if callable(method):
                method(first_waypoint.coordinate.copy())
                break

        if hasattr(agent, "target_waypoint"):
            agent.target_waypoint = first_waypoint.coordinate.copy()
        if hasattr(agent, "current_waypoint"):
            agent.current_waypoint = first_waypoint.coordinate.copy()
        if hasattr(agent, "mission_status"):
            agent.mission_status = self._coerce_enum_value(
                getattr(agent, "mission_status"),
                "ACTIVE",
            )
        self._set_agent_mode(agent, "PATROL")

    def _handle_physics_events(self, events: list[SimEvent]) -> None:
        """Apply engine-side reactions to physics events."""
        for event in events:
            if event.event_type != GEOFENCE_VIOLATION_EVENT:
                continue
            if event.uav_id is None:
                continue

            agent = self.uav_registry.get(event.uav_id)
            if agent is None:
                continue
            self._trigger_hover(agent, "geofence violation")
            event.details["action"] = "HOVER"

    def _trigger_hover(self, agent: object, reason: str) -> None:
        """Move a UAV into hover using local or branch-specific hooks."""
        for method_name in ("triggerHover", "trigger_hover", "hover"):
            method = getattr(agent, method_name, None)
            if callable(method):
                self._call_optional_reason_method(method, reason)
                return
        self._set_agent_mode(agent, "HOVER")

    def _update_threat_detectors(
        self,
        uav_states: dict[int, UAVState],
    ) -> list[SimEvent]:
        """Run registered or agent-attached ThreatDetector objects."""
        events: list[SimEvent] = []
        sim_objects = self._build_threat_detector_objects()
        detectors = self._collect_threat_detectors()

        for uav_id, detector in detectors.items():
            state = uav_states.get(uav_id)
            update_method = getattr(detector, "update", None)
            if state is None or not callable(update_method):
                continue

            try:
                result = update_method(state.position.copy(), sim_objects)
                events.extend(self._coerce_detector_events(result, uav_id))
            except Exception as exc:
                events.append(
                    self._build_error_event(
                        "ThreatDetector",
                        exc,
                        uav_id=uav_id,
                    )
                )

        return events

    def _collect_threat_detectors(self) -> dict[int, object]:
        """Return explicitly registered and agent-attached threat detectors."""
        detectors = dict(self._threat_detectors)
        for uav_id, agent in self.uav_registry.items():
            for attr_name in ("threat_detector", "threatDetector", "detector"):
                detector = getattr(agent, attr_name, None)
                if detector is not None:
                    detectors.setdefault(uav_id, detector)
                    break
        return detectors

    def _build_threat_detector_objects(self) -> list[dict[str, object]]:
        """Convert SimObject models to the dict shape used by ThreatDetector."""
        objects: list[dict[str, object]] = []
        for sim_object in self.environment.sim_objects.values():
            payload = {
                "id": sim_object.object_id,
                "lat": sim_object.position.latitude,
                "lon": sim_object.position.longitude,
                "alt": sim_object.position.altitude,
                "radius_m": sim_object.radius_m,
            }
            payload.update(sim_object.metadata)
            objects.append(payload)
        return objects

    def _coerce_detector_events(
        self,
        result: object,
        uav_id: int,
    ) -> list[SimEvent]:
        """Convert optional detector return values into SimEvent objects."""
        if result is None:
            return []
        if isinstance(result, SimEvent):
            return [result]
        if not isinstance(result, list):
            return []

        events: list[SimEvent] = []
        for item in result:
            if isinstance(item, SimEvent):
                events.append(item)
            else:
                events.append(
                    SimEvent(
                        event_type=THREAT_DETECTED_EVENT,
                        uav_id=uav_id,
                        details={"alert": item},
                    )
                )
        return events

    def _should_complete_mission(self) -> bool:
        """Return True when every registered UAV has finished its route."""
        if self._mission_status != "ACTIVE":
            return False
        if not self.uav_registry:
            return False
        return all(
            self._agent_route_complete(agent)
            for agent in self.uav_registry.values()
        )

    def _agent_route_complete(self, agent: object) -> bool:
        """Infer whether an agent has completed all mission waypoints."""
        mission_status = _enum_or_value(
            getattr(agent, "mission_status", None),
            "",
        )
        if mission_status == "COMPLETED":
            return True

        for attr_name in ("completed", "is_complete", "route_complete"):
            value = getattr(agent, attr_name, None)
            if isinstance(value, bool) and value:
                return True

        navigation = getattr(agent, "navigation", None)
        current_waypoint = getattr(navigation, "current_waypoint", None)
        if callable(current_waypoint) and current_waypoint() is None:
            return True

        return False

    def _update_registered_agents(self, delta_time_s: float) -> None:
        """Invoke UAVAgent update/tick hooks before physics advances state."""
        obstacle_positions: list[GeoCoordinate] | None = None

        for agent in self.uav_registry.values():
            try:
                update_method = getattr(agent, "update", None)
                if callable(update_method):
                    self._call_update_method(update_method, delta_time_s)
                    continue

                tick_method = getattr(agent, "tick", None)
                if callable(tick_method):
                    if obstacle_positions is None:
                        obstacle_positions = self._collect_obstacle_positions()
                    self._call_tick_method(
                        tick_method,
                        delta_time_s,
                        obstacle_positions,
                    )
            except Exception as exc:
                self._record_event(
                    self._build_error_event(
                        "UAVAgent",
                        exc,
                        uav_id=self._safe_agent_id(agent),
                    )
                )

    def _collect_obstacle_positions(self) -> list[GeoCoordinate]:
        """Return sim object positions in the shape expected by UAVAgent.tick()."""
        return [
            sim_object.position.copy()
            for sim_object in self.environment.sim_objects.values()
        ]

    def _build_telemetry_packet(
        self,
        state: UAVState,
        timestamp_ms: int,
    ) -> object:
        """Create the branch-provided TelemetryPacket when available."""
        fallback_packet = self._build_telemetry_dict(state, timestamp_ms)

        try:
            from atlas_communication import telemetry_packet as telemetry_module
        except ImportError:
            return fallback_packet

        telemetry_packet_type = getattr(telemetry_module, "TelemetryPacket", None)
        if telemetry_packet_type is None:
            return fallback_packet

        try:
            return telemetry_packet_type(
                uav_id=state.uav_id,
                position=self._build_external_coordinate(
                    getattr(telemetry_module, "GeoCoordinate", None),
                    state.position,
                ),
                velocity=self._build_external_vector(
                    getattr(telemetry_module, "Vector3D", None),
                    state.velocity,
                ),
                battery_level=state.battery_level,
                flight_mode=self._build_external_flight_mode(
                    getattr(telemetry_module, "FlightMode", None),
                    state.flight_mode,
                ),
                timestamp=timestamp_ms,
            )
        except (TypeError, ValueError, AttributeError):
            return fallback_packet

    @staticmethod
    def _build_telemetry_dict(state: UAVState, timestamp_ms: int) -> dict[str, object]:
        """Fallback telemetry payload used before atlas_communication is installed."""
        return {
            "timestamp": timestamp_ms,
            "uav_id": state.uav_id,
            "position": state.position.copy(),
            "velocity": state.velocity.copy(),
            "heading": state.heading,
            "battery_level": state.battery_level,
            "flight_mode": state.flight_mode,
            "system_status": state.system_status,
        }

    def _log_telemetry_packets(
        self,
        telemetry_packets: list[object],
        should_flush: bool,
    ) -> None:
        """Send telemetry payloads to DataLogger when that package is present."""
        if not telemetry_packets:
            return

        logger = self._get_data_logger()
        if logger is None:
            return

        log_method = getattr(logger, "log_flight_data", None)
        if not callable(log_method):
            log_method = getattr(logger, "logFlightData", None)
        if not callable(log_method):
            return

        for packet in telemetry_packets:
            try:
                log_method(packet)
            except Exception as exc:
                self._record_event(
                    self._build_error_event("DataLogger.telemetry", exc)
                )

        if should_flush:
            self._flush_data_logger(logger)

    def _log_events(self, events: list[SimEvent]) -> None:
        """Write simulation events to DataLogger when available."""
        if not events:
            return

        logger = self._get_data_logger()
        if logger is None:
            return

        log_incident = getattr(logger, "log_incident", None)
        if not callable(log_incident):
            return

        for event in events:
            try:
                log_incident(
                    incident_type=event.event_type,
                    uav_id=event.uav_id if event.uav_id is not None else "SIM",
                    details=str(event.details),
                )
            except Exception as exc:
                self._record_event(
                    self._build_error_event("DataLogger.events", exc)
                )

    def _get_data_logger(self) -> object | None:
        """Resolve DataLogger lazily so simulation stays usable without atlas_data."""
        if self._data_logger is not None:
            return self._data_logger
        if not self._data_logger_available:
            return None

        data_logger_type = self._import_data_logger_type()
        if data_logger_type is None:
            self._data_logger_available = False
            return None

        get_instance = getattr(data_logger_type, "get_instance", None)
        if not callable(get_instance):
            self._data_logger_available = False
            return None

        self._data_logger = get_instance()
        return self._data_logger

    def _flush_data_logger(self, logger: object | None = None) -> None:
        """Flush DataLogger buffers when logging has been activated."""
        target_logger = logger if logger is not None else self._data_logger
        if target_logger is None:
            return

        flush = getattr(target_logger, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:
                return

    def _record_event(self, event: SimEvent) -> SimEvent:
        """Append an event to the current tick buffer with metadata."""
        timestamp_ms = int(time.time() * 1000)
        with self._lock:
            if event.tick == 0:
                event.tick = self.current_tick
            if event.timestamp_ms == 0:
                event.timestamp_ms = timestamp_ms
            self.pending_events.append(event)
        return event

    def _record_and_log_event(self, event: SimEvent) -> SimEvent:
        """Record an event and immediately send it to the logger."""
        recorded_event = self._record_event(event)
        self._log_events([recorded_event.copy()])
        return recorded_event

    def _build_error_event(
        self,
        subsystem: str,
        exc: Exception,
        uav_id: int | None = None,
    ) -> SimEvent:
        """Create a resilient-loop error event."""
        return SimEvent(
            event_type=SUBSYSTEM_ERROR_EVENT,
            tick=self.current_tick,
            timestamp_ms=int(time.time() * 1000),
            uav_id=uav_id,
            details={
                "subsystem": subsystem,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    def _safe_publish_telemetry(self, packet: object) -> None:
        """Publish telemetry without letting bus failures stop the tick."""
        try:
            publish_telemetry(packet)
        except Exception as exc:
            self._record_and_log_event(
                self._build_error_event("CommunicationBus.telemetry", exc)
            )

    def _safe_publish_world_state(self, world_state: WorldState) -> None:
        """Publish world state without letting bus failures stop the tick."""
        try:
            publish_world_state(world_state)
        except Exception as exc:
            self._record_and_log_event(
                self._build_error_event("CommunicationBus.world_state", exc)
            )

    def _safe_publish_emergency_event(self, event: SimEvent) -> None:
        """Publish emergency events without coupling engine health to the bus."""
        try:
            publish_emergency_event(event)
        except Exception as exc:
            self._record_and_log_event(
                self._build_error_event("CommunicationBus.emergency", exc)
            )

    def _safe_dispatch_messages(self) -> None:
        """Dispatch queued bus messages without stopping the simulation."""
        try:
            dispatch_messages()
        except Exception as exc:
            self._record_and_log_event(
                self._build_error_event("CommunicationBus.dispatch", exc)
            )

    def _collect_uav_states(self) -> dict[int, UAVState]:
        """Normalize registered agents into internal UAVState objects."""
        collected_states: dict[int, UAVState] = {}

        for uav_id, agent in self.uav_registry.items():
            previous_state = None
            if self._last_world_state is not None:
                previous_state = self._last_world_state.uav_states.get(uav_id)

            position = self._read_coordinate(getattr(agent, "position", None))
            velocity = self._read_vector(getattr(agent, "velocity", None))
            heading = float(getattr(agent, "heading", 0.0))
            battery_level = self._read_battery_level(agent)
            flight_mode = _enum_or_value(
                getattr(agent, "flight_mode", None),
                "PATROL",
            )
            system_status = _enum_or_value(
                getattr(agent, "system_status", None),
                "ACTIVE",
            )
            last_valid_position = (
                previous_state.last_valid_position.copy()
                if previous_state is not None
                else position.copy()
            )

            collected_states[uav_id] = UAVState(
                uav_id=uav_id,
                position=position,
                velocity=velocity,
                heading=heading,
                battery_level=battery_level,
                flight_mode=flight_mode,
                system_status=system_status,
                last_valid_position=last_valid_position,
            )

        return collected_states

    def _sync_uav_states(self, uav_states: dict[int, UAVState]) -> None:
        """Write updated states back to registered agent objects."""
        for uav_id, state in uav_states.items():
            agent = self.uav_registry[uav_id]
            self._write_back_state(agent, state)

    def _stamp_events(self, events: list[SimEvent], timestamp_ms: int) -> None:
        """Attach tick metadata to generated events."""
        for event in events:
            event.tick = self.current_tick
            event.timestamp_ms = timestamp_ms

    @staticmethod
    def _call_optional_reason_method(method: object, reason: str) -> None:
        """Call a recovery hook with a reason only when it accepts one."""
        if SimulationEngine._parameter_names(method):
            method(reason)
        else:
            method()

    @staticmethod
    def _set_agent_mode(agent: object, mode: str) -> None:
        """Set flight_mode while preserving enum-backed branch models."""
        current_mode = getattr(agent, "flight_mode", None)
        coerced_mode = SimulationEngine._coerce_enum_value(current_mode, mode)
        setattr(agent, "flight_mode", coerced_mode)

    @staticmethod
    def _coerce_enum_value(current_value: object, value: str) -> object:
        """Convert a string into the enum class already used by an object."""
        if current_value is None:
            return value

        enum_type = type(current_value)
        try:
            return enum_type(value)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _safe_agent_id(agent: object) -> int | None:
        """Best-effort integer UAV id extraction for error events."""
        try:
            return SimulationEngine._normalize_uav_id(agent)
        except (AttributeError, ValueError):
            return None

    @staticmethod
    def _call_update_method(method: object, delta_time_s: float) -> None:
        """Call update(delta_time) while tolerating no-arg update hooks."""
        if SimulationEngine._parameter_names(method):
            method(delta_time_s)
        else:
            method()

    @staticmethod
    def _call_tick_method(
        method: object,
        delta_time_s: float,
        obstacle_positions: list[GeoCoordinate],
    ) -> None:
        """Call tick() variants used by the UAV branch."""
        parameter_names = SimulationEngine._parameter_names(method)
        if not parameter_names:
            method()
            return

        first_name = parameter_names[0]
        if first_name in {"delta_time", "delta_time_s", "deltaTime", "dt"}:
            method(delta_time_s)
        else:
            method(obstacle_positions)

    @staticmethod
    def _parameter_names(method: object) -> list[str]:
        """Return callable parameter names, excluding varargs-only details."""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return []

        return [
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

    @staticmethod
    def _build_external_coordinate(
        coordinate_type: object | None,
        position: GeoCoordinate,
    ) -> object:
        """Instantiate either common.GeoCoordinate or older lat/lon DTOs."""
        if coordinate_type is None:
            return position.copy()

        try:
            return coordinate_type(
                latitude=position.latitude,
                longitude=position.longitude,
                altitude=position.altitude,
            )
        except TypeError:
            return coordinate_type(
                lat=position.latitude,
                lon=position.longitude,
                alt=position.altitude,
            )

    @staticmethod
    def _build_external_vector(
        vector_type: object | None,
        velocity: Vector3D,
    ) -> object:
        """Instantiate branch Vector3D DTOs without coupling to their package."""
        if vector_type is None:
            return velocity.copy()
        return vector_type(x=velocity.x, y=velocity.y, z=velocity.z)

    @staticmethod
    def _build_external_flight_mode(
        flight_mode_type: object | None,
        flight_mode: object,
    ) -> object:
        """Coerce local flight-mode values into the communication enum if present."""
        mode_value = _enum_or_value(flight_mode, "PATROL")
        if flight_mode_type is None:
            return mode_value

        try:
            return flight_mode_type(mode_value)
        except (TypeError, ValueError):
            return mode_value

    @staticmethod
    def _import_data_logger_type() -> object | None:
        """Import DataLogger from either package export style."""
        for module_name in ("atlas_data", "atlas_data.data_logger"):
            try:
                module = __import__(module_name, fromlist=["DataLogger"])
            except ImportError:
                continue

            data_logger_type = getattr(module, "DataLogger", None)
            if data_logger_type is not None:
                return data_logger_type
        return None

    @staticmethod
    def _read_value(raw: object, key: str, default: object = None) -> object:
        """Read a key from dict-like or attribute-backed objects."""
        if isinstance(raw, dict):
            return raw.get(key, default)
        return getattr(raw, key, default)

    @staticmethod
    def _normalize_uav_id(agent: object) -> int:
        """Extract a stable integer UAV id from an agent."""
        if not hasattr(agent, "uav_id"):
            raise AttributeError("Registered UAV must expose a 'uav_id' attribute")
        try:
            return int(getattr(agent, "uav_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("uav_id must be convertible to int") from exc

    @staticmethod
    def _read_coordinate(raw: object) -> GeoCoordinate:
        """Read a coordinate from either lat/lon or latitude/longitude fields."""
        if raw is None:
            return GeoCoordinate(0.0, 0.0, 0.0)

        if isinstance(raw, dict):
            latitude = raw.get("latitude", raw.get("lat", 0.0))
            longitude = raw.get("longitude", raw.get("lon", 0.0))
            altitude = raw.get("altitude", raw.get("alt", 0.0))
        else:
            latitude = getattr(raw, "latitude", getattr(raw, "lat", 0.0))
            longitude = getattr(raw, "longitude", getattr(raw, "lon", 0.0))
            altitude = getattr(raw, "altitude", getattr(raw, "alt", 0.0))
        return GeoCoordinate(float(latitude), float(longitude), float(altitude))

    @staticmethod
    def _read_vector(raw: object) -> Vector3D:
        """Read a vector from an object exposing x/y/z values."""
        if raw is None:
            return Vector3D(0.0, 0.0, 0.0)
        if isinstance(raw, dict):
            return Vector3D(
                float(raw.get("x", 0.0)),
                float(raw.get("y", 0.0)),
                float(raw.get("z", 0.0)),
            )
        return Vector3D(
            float(getattr(raw, "x", 0.0)),
            float(getattr(raw, "y", 0.0)),
            float(getattr(raw, "z", 0.0)),
        )

    @staticmethod
    def _read_battery_level(agent: object) -> float:
        """Read battery level from common field names."""
        if hasattr(agent, "battery_level"):
            return float(getattr(agent, "battery_level"))
        if hasattr(agent, "battery_pct"):
            return float(getattr(agent, "battery_pct"))
        return 100.0

    @staticmethod
    def _write_back_state(agent: object, state: UAVState) -> None:
        """Write updated position and velocity back onto the agent object."""
        if hasattr(agent, "position") and getattr(agent, "position") is not None:
            position = getattr(agent, "position")
            if hasattr(position, "latitude"):
                position.latitude = state.position.latitude
                position.longitude = state.position.longitude
                position.altitude = state.position.altitude
            elif hasattr(position, "lat"):
                position.lat = state.position.latitude
                position.lon = state.position.longitude
                position.alt = state.position.altitude
            else:
                agent.position = state.position.copy()
        else:
            agent.position = state.position.copy()

        if hasattr(agent, "velocity") and getattr(agent, "velocity") is not None:
            velocity = getattr(agent, "velocity")
            if hasattr(velocity, "x"):
                velocity.x = state.velocity.x
                velocity.y = state.velocity.y
                velocity.z = state.velocity.z
            else:
                agent.velocity = state.velocity.copy()
        else:
            agent.velocity = state.velocity.copy()

        if hasattr(agent, "heading"):
            agent.heading = state.heading
