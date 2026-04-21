from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DataLogger:
    flight_log_path: Path
    event_log_path: Path
    telemetry_buffer: list[dict[str, Any]] = field(default_factory=list)
    event_buffer: list[dict[str, Any]] = field(default_factory=list)

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

    def log_flight_data(self, packet_or_dict: dict[str, Any]) -> None:
        row = {field: packet_or_dict.get(field) for field in self.TELEMETRY_FIELDS}
        self.telemetry_buffer.append(row)

    def log_threat_event(self, alert_or_dict: dict[str, Any]) -> None:
        record = {
            "event_type": "threat_event",
            **alert_or_dict,
        }
        self.event_buffer.append(record)

    def log_incident(self, incident_type: str, uav_id: int | str, details: str) -> None:
        record = {
            "event_type": "incident",
            "incident_type": incident_type,
            "uav_id": uav_id,
            "details": details,
        }
        self.event_buffer.append(record)

    def flush(self) -> None:
        self._flush_telemetry()
        self._flush_events()

    def _flush_telemetry(self) -> None:
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
        if not self.event_buffer:
            return

        with self.event_log_path.open("a", encoding="utf-8") as jsonl_file:
            for record in self.event_buffer:
                jsonl_file.write(json.dumps(record) + "\n")

        self.event_buffer.clear()
