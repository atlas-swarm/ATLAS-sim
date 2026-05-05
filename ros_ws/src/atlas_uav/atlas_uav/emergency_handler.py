"""Handles abnormal conditions and triggers safe-state transitions."""

from dataclasses import dataclass, field
from datetime import datetime

from atlas_common.enums import FlightMode


@dataclass
class EmergencyHandler:
    """Evaluates fault conditions and recommends recovery flight modes."""

    uav_id: str
    battery_rtl_threshold: float = 20.0  # percent
    _active_faults: list[str] = field(default_factory=list, init=False, repr=False)

    def report_fault(self, fault: str) -> None:
        """Record a new fault with a timestamp."""
        entry = f"[{datetime.utcnow().isoformat()}] {fault}"
        self._active_faults.append(entry)

    def recommend_mode(self, battery_pct: float) -> FlightMode:
        """Return the safest flight mode given current faults and battery level."""
        if battery_pct <= 0:
            return FlightMode.LAND
        if battery_pct <= self.battery_rtl_threshold or self._active_faults:
            return FlightMode.RTL
        return FlightMode.PATROL

    def clear_faults(self) -> None:
        """Remove all recorded faults after successful recovery."""
        self._active_faults.clear()

    @property
    def has_active_faults(self) -> bool:
        return bool(self._active_faults)
