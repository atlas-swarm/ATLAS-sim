"""Handles abnormal conditions and triggers safe-state transitions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from atlas_common.enums import FlightMode


@dataclass
class EmergencyHandler:
    """Evaluates fault conditions and recommends recovery flight modes."""

    uav_id: str
    battery_rtl_threshold: float = 20.0  # percent
    _active_faults: list[str] = field(default_factory=list, init=False, repr=False)
    on_uav_lost: Optional[Callable[[str], None]] = field(
        default=None, init=False, repr=False
    )

    def report_fault(self, fault: str) -> None:
        """Record a new fault with a timestamp."""
        entry = f"[{datetime.utcnow().isoformat()}] {fault}"
        self._active_faults.append(entry)

    def recommend_mode(self, battery_pct: float) -> FlightMode:
        """Return the safest flight mode given current faults and battery level."""
        if battery_pct <= 0:
            self._fire_uav_lost()
            return FlightMode.LAND
        if battery_pct <= self.battery_rtl_threshold or self._active_faults:
            self._fire_uav_lost()
            return FlightMode.RTL
        return FlightMode.PATROL

    def _fire_uav_lost(self) -> None:
        if self.on_uav_lost is not None:
            self.on_uav_lost(self.uav_id)
            self.on_uav_lost = None  # tek seferlik

    def clear_faults(self) -> None:
        """Remove all recorded faults after successful recovery."""
        self._active_faults.clear()

    @property
    def has_active_faults(self) -> bool:
        return bool(self._active_faults)
