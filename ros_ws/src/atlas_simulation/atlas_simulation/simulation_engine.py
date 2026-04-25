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
    publish_telemetry,
    publish_world_state,
)


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
            new_events = self.physics_processor.update_positions(
                uav_states=uav_states,
                delta_time_s=delta_time_s,
                environment=self.environment,
            )
            self._stamp_events(new_events, timestamp_ms)
            self.pending_events.extend(new_events)
            self._sync_uav_states(uav_states)
            telemetry_packets = [
                self._build_telemetry_packet(state, timestamp_ms)
                for state in uav_states.values()
            ]
            should_flush_logger = self.current_tick % 10 == 0

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
            publish_telemetry(packet)
        self._log_telemetry_packets(telemetry_packets, should_flush_logger)
        publish_world_state(published_world_state)
        dispatch_messages()
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
                timestamp_ms = int(time.time() * 1000)
                with self._lock:
                    self.pending_events = [
                        SimEvent(
                            event_type="SIMULATION_ERROR",
                            tick=self.current_tick,
                            timestamp_ms=timestamp_ms,
                            details={"error": str(exc)},
                        )
                    ]
                    self.is_paused = True

            elapsed = time.monotonic() - start_time
            sleep_s = max(0.0, self.tick_interval_ms / 1000.0 - elapsed)
            if sleep_s > 0:
                self._loop_state.stop_event.wait(timeout=sleep_s)

    def _update_registered_agents(self, delta_time_s: float) -> None:
        """Invoke UAVAgent update/tick hooks before physics advances state."""
        obstacle_positions: list[GeoCoordinate] | None = None

        for agent in self.uav_registry.values():
            update_method = getattr(agent, "update", None)
            if callable(update_method):
                self._call_update_method(update_method, delta_time_s)
                continue

            tick_method = getattr(agent, "tick", None)
            if callable(tick_method):
                if obstacle_positions is None:
                    obstacle_positions = self._collect_obstacle_positions()
                self._call_tick_method(tick_method, delta_time_s, obstacle_positions)

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
            log_method(packet)

        if should_flush:
            self._flush_data_logger(logger)

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
            flush()

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

        latitude = getattr(raw, "latitude", getattr(raw, "lat", 0.0))
        longitude = getattr(raw, "longitude", getattr(raw, "lon", 0.0))
        altitude = getattr(raw, "altitude", getattr(raw, "alt", 0.0))
        return GeoCoordinate(float(latitude), float(longitude), float(altitude))

    @staticmethod
    def _read_vector(raw: object) -> Vector3D:
        """Read a vector from an object exposing x/y/z values."""
        if raw is None:
            return Vector3D(0.0, 0.0, 0.0)
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
