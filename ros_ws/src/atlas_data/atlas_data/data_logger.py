from __future__ import annotations

import csv
import json
import shutil
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
            if flight_log_path is None or event_log_path is None:
                raise ValueError(
                    "flight_log_path and event_log_path must be provided when creating the first instance"
                )
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
        
        row = {field: data.get(field) for field in self.TELEMETRY_FIELDS}
        self.telemetry_buffer.append(row)

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
        
        record = {
            "event_type": "threat_event",
            **data,
        }
        self.event_buffer.append(record)

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

    def flush(self) -> None:
        """Flush both telemetry and event buffers to disk."""
        self._flush_telemetry()
        self._flush_events()

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
