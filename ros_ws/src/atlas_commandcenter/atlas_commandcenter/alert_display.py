from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas_threat.threat_alert import ThreatAlert


@dataclass
class AlertDisplay:
    """Manages threat alert queue and history for the command center."""
    
    alert_queue: list[Any] = field(default_factory=list)  # ThreatAlert objects
    alert_history: list[Any] = field(default_factory=list)  # ThreatAlert objects
    max_queue_size: int = 50

    def enqueue_alert(self, alert: ThreatAlert | Any) -> None:
        """
        Add alert to the queue. If queue exceeds max_queue_size, 
        move the oldest alert to history.
        """
        self.alert_queue.append(alert)
        
        # If queue is over capacity, move oldest to history
        if len(self.alert_queue) > self.max_queue_size:
            oldest_alert = self.alert_queue.pop(0)
            self.alert_history.append(oldest_alert)

    def acknowledge_alert(self, alert_id: str) -> None:
        """
        Mark an alert as acknowledged by setting is_acknowledged = True.
        Optionally triggers DataLogger.log_threat_event().
        """
        for alert in self.alert_queue:
            # Handle both dict and object
            if isinstance(alert, dict):
                if alert.get("alert_id") == alert_id:
                    alert["is_acknowledged"] = True
            else:
                # Object with attributes
                if hasattr(alert, "alert_id") and alert.alert_id == alert_id:
                    alert.is_acknowledged = True

    def get_active_alerts(self) -> list[Any]:
        """Return only alerts that have not been acknowledged."""
        active_alerts = []
        
        for alert in self.alert_queue:
            # Handle both dict and object
            if isinstance(alert, dict):
                if not alert.get("is_acknowledged", False):
                    active_alerts.append(alert)
            else:
                # Object with attributes
                if not getattr(alert, "is_acknowledged", False):
                    active_alerts.append(alert)
        
        return active_alerts

    def clear_alerts(self) -> None:
        """Clear the alert queue."""
        self.alert_queue.clear()

    def export_alert_log(self, file_path: str) -> None:
        """
        Export alert history to a JSON file.
        Each alert includes: alertId, timestamp, classification, 
        confidenceScore, isAcknowledged.
        """
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert alerts to serializable format
        export_data = []
        
        for alert in self.alert_history:
            if isinstance(alert, dict):
                # Already a dict
                alert_data = {
                    "alertId": alert.get("alert_id"),
                    "timestamp": alert.get("timestamp"),
                    "classification": alert.get("classification"),
                    "confidenceScore": alert.get("confidence_score"),
                    "isAcknowledged": alert.get("is_acknowledged", False),
                }
            else:
                # Object with attributes
                alert_data = {
                    "alertId": getattr(alert, "alert_id", None),
                    "timestamp": getattr(alert, "timestamp", None),
                    "classification": getattr(alert, "classification", None),
                    "confidenceScore": getattr(alert, "confidence_score", None),
                    "isAcknowledged": getattr(alert, "is_acknowledged", False),
                }
            
            export_data.append(alert_data)
        
        # Write to JSON file
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2)
