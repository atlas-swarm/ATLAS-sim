from __future__ import annotations

import csv
import json
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from atlas_communication.telemetry_packet import TelemetryPacket
    from atlas_threat.threat_alert import ThreatAlert


class LogFormat(str, Enum):
    CSV = "CSV"
    ULOG = "ULOG"


@dataclass
class DataLogger:
    # Singleton instance
    _instance: ClassVar[DataLogger | None] = None

    # Required attributes
    flight_log_path: Path
    event_log_path: Path

    # Optional attributes
    output_format: LogFormat = LogFormat.CSV
    buffer_flush_interval_ms: int = 1000
    telemetry_buffer: list[dict[str, Any]] = field(default_factory=list)
    event_buffer: list[dict[str, Any]] = field(default_factory=list)
    _closed: bool = field(default=False, init=False)
    _last_flush_time: float = field(default_factory=time.monotonic, init=False)

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

    def __post_init__(self) -> None:
        self.flight_log_path = Path(self.flight_log_path)
        self.event_log_path = Path(self.event_log_path)

        self.flight_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(
        cls,
        flight_log_path: Path | str | None = None,
        event_log_path: Path | str | None = None,
        **kwargs: Any,
    ) -> DataLogger:
        """Get the singleton instance of DataLogger. Creates it if it doesn't exist."""
        if cls._instance is None:
            if flight_log_path is None:
                flight_log_path = Path("logs/flight_log.csv")
            if event_log_path is None:
                event_log_path = Path("logs/event_log.jsonl")
            
            cls._instance = cls(
                flight_log_path=Path(flight_log_path),
                event_log_path=Path(event_log_path),
                **kwargs,
            )
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. For testing purposes only."""
        cls._instance = None

    def log_flight_data(self, packet: TelemetryPacket | dict[str, Any]) -> None:
        """Log flight telemetry data. Accepts TelemetryPacket object or dict."""
        # Duck typing: handle both TelemetryPacket objects and dicts
        if isinstance(packet, dict):
            data = packet
        else:
            # Try to convert object to dict
            try:
                from dataclasses import asdict
                data = asdict(packet)
            except Exception:
                # Fallback to vars() for non-dataclass objects
                data = vars(packet)
        
        # Extract fields, handling nested position and velocity
        row = {}
        for field in self.TELEMETRY_FIELDS:
            if field in data:
                value = data[field]
                row[field] = value.value if hasattr(value, "value") else value
            elif field == "latitude" and "position" in data:
                pos = data["position"]
                row[field] = pos.latitude if hasattr(pos, "latitude") else pos.get("latitude")
            elif field == "longitude" and "position" in data:
                pos = data["position"]
                row[field] = pos.longitude if hasattr(pos, "longitude") else pos.get("longitude")
            elif field == "altitude" and "position" in data:
                pos = data["position"]
                row[field] = pos.altitude if hasattr(pos, "altitude") else pos.get("altitude")
            elif field == "velocity_x" and "velocity" in data:
                vel = data["velocity"]
                row[field] = vel.x if hasattr(vel, "x") else vel.get("x")
            elif field == "velocity_y" and "velocity" in data:
                vel = data["velocity"]
                row[field] = vel.y if hasattr(vel, "y") else vel.get("y")
            elif field == "velocity_z" and "velocity" in data:
                vel = data["velocity"]
                row[field] = vel.z if hasattr(vel, "z") else vel.get("z")
            else:
                row[field] = None

        # Current TelemetryPacket does not provide heading/system_status; leave them as None.
        
        self.telemetry_buffer.append(row)
        self._maybe_flush()

    def log_threat_event(self, alert: ThreatAlert | dict[str, Any]) -> None:
        """Log threat event. Accepts ThreatAlert object or dict."""
        # Duck typing: handle both ThreatAlert objects and dicts
        if isinstance(alert, dict):
            data = alert
        else:
            # Try to convert object to dict
            try:
                from dataclasses import asdict
                data = asdict(alert)
            except Exception:
                # Fallback to vars() for non-dataclass objects
                data = vars(alert)
        
        # Normalize threat_coordinates if it's a GeoCoordinate object
        threat_coords = data.get("threat_coordinates")
        if threat_coords and not isinstance(threat_coords, dict):
            if hasattr(threat_coords, "latitude"):
                data["threat_coordinates"] = {
                    "latitude": threat_coords.latitude,
                    "longitude": threat_coords.longitude,
                    "altitude": threat_coords.altitude,
                }
        
        record = {
            "event_type": "threat_event",
            "alert_id": data.get("alert_id"),
            "detected_by_uav_id": data.get("detected_by_uav_id"),
            "timestamp": data.get("timestamp"),
            "threat_coordinates": data.get("threat_coordinates"),
            "classification": data.get("classification"),
            "confidence_score": data.get("confidence_score"),
            "is_acknowledged": data.get("is_acknowledged", False),
        }
        self.event_buffer.append(record)
        self._maybe_flush()

    def log_incident(
        self,
        incident_type: str | Any,
        uav_id: int | str,
        details: str,
    ) -> None:
        """Log incident. Accepts IncidentType enum or plain string for incident_type."""
        # Handle both IncidentType enum and string
        if isinstance(incident_type, str):
            incident_type_str = incident_type
        else:
            # Assume it's an enum with .value attribute
            try:
                incident_type_str = incident_type.value
            except AttributeError:
                incident_type_str = str(incident_type)
        
        record = {
            "event_type": "incident",
            "incident_type": incident_type_str,
            "uav_id": uav_id,
            "details": details,
        }
        self.event_buffer.append(record)
        self._maybe_flush()

    def flush(self) -> None:
        """Flush both telemetry and event buffers to disk."""
        self._flush_telemetry()
        self._flush_events()
        self._last_flush_time = time.monotonic()

    def close(self) -> None:
        """Close the logger: flush all buffers and mark as closed."""
        self.flush()
        self._closed = True

    def export_to_csv(self, output_path: str) -> None:
        """Export flight log to the specified CSV file path."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        # Flush any pending data first
        self.flush()
        
        # Copy the flight log to the output path
        if self.flight_log_path.exists():
            shutil.copy2(self.flight_log_path, output)

    def _flush_telemetry(self) -> None:
        """Flush telemetry buffer to CSV file. EXISTING LOGIC PRESERVED."""
        if not self.telemetry_buffer:
            return

        file_exists = self.flight_log_path.exists() and self.flight_log_path.stat().st_size > 0

        with self.flight_log_path.open("a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.TELEMETRY_FIELDS)

            if not file_exists:
                writer.writeheader()

            writer.writerows(self.telemetry_buffer)

        self.telemetry_buffer.clear()

    def _flush_events(self) -> None:
        """Flush event buffer to JSONL file. EXISTING LOGIC PRESERVED."""
        if not self.event_buffer:
            return

        with self.event_log_path.open("a", encoding="utf-8") as jsonl_file:
            for record in self.event_buffer:
                jsonl_file.write(json.dumps(record) + "\n")

        self.event_buffer.clear()

    def _maybe_flush(self) -> None:
        """Flush buffers when the configured flush interval has elapsed."""
        if self._closed:
            return

        if self.buffer_flush_interval_ms <= 0:
            return

        elapsed_ms = (time.monotonic() - self._last_flush_time) * 1000
        if elapsed_ms >= self.buffer_flush_interval_ms:
            self.flush()
