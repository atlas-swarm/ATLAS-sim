from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from atlas_commandcenter.alert_display import AlertDisplay
from atlas_commandcenter.mission_controller import MissionController
from atlas_data import MissionPlan

if TYPE_CHECKING:
    from atlas_communication.communication_bus import CommunicationBus
    from atlas_threat.threat_alert import ThreatAlert


@dataclass
class CommandCenterInterface:
    """
    Singleton Facade for the command center.
    Provides unified interface for mission control, alert management, and telemetry monitoring.
    """
    
    # Singleton instance
    _instance: ClassVar[CommandCenterInterface | None] = None
    
    # Core components
    mission_controller: MissionController = field(default_factory=MissionController)
    alert_display: AlertDisplay = field(default_factory=AlertDisplay)
    telemetry_feed: list[Any] = field(default_factory=list)  # TelemetryPacket objects
    is_connected: bool = False

    @classmethod
    def get_instance(cls) -> CommandCenterInterface:
        """Get the singleton instance of CommandCenterInterface."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def connect_to_engine(self, host: str, port: int) -> None:
        """
        Connect to the simulation engine via CommunicationBus.
        Subscribes to TELEMETRY and THREAT_ALERT message types.
        """
        try:
            from atlas_communication.communication_bus import CommunicationBus
            from atlas_common import MessageType
            
            bus = CommunicationBus.get_instance()
            
            # Subscribe to TELEMETRY messages
            bus.subscribe(MessageType.TELEMETRY, self._on_telemetry)
            
            # Subscribe to THREAT_ALERT messages
            bus.subscribe(MessageType.THREAT_ALERT, self.on_alert_received)
            
            # Subscribe to WORLD_STATE messages (as per CLAUDE.md Section 5.1)
            bus.subscribe(MessageType.WORLD_STATE, self._on_world_state)
            
            self.is_connected = True
            print(f"Connected to simulation engine at {host}:{port}")
            
        except ImportError:
            # CommunicationBus not available yet - graceful degradation
            self.is_connected = False
            print("WARNING: CommunicationBus not available, connection failed")
        except Exception as e:
            self.is_connected = False
            print(f"ERROR: Failed to connect to engine: {e}")

    def disconnect(self) -> None:
        """Disconnect from the simulation engine."""
        self.is_connected = False
        print("Disconnected from simulation engine")

    def load_mission_plan(self, file_path: str) -> MissionPlan:
        """Load a mission plan from a JSON file."""
        return MissionPlan.load_json(file_path)

    def upload_mission(self, plan: MissionPlan) -> bool:
        """
        Upload and validate a mission plan.
        Returns True if plan is valid and uploaded successfully.
        """
        if self.mission_controller.validate_plan(plan):
            self.mission_controller.active_plan = plan
            self.mission_controller.patrol_boundary = plan.patrol_boundary
            print(f"Mission plan '{plan.mission_id}' uploaded successfully")
            return True
        else:
            print("ERROR: Mission plan validation failed")
            return False

    def display_swarm_status(self, packets: list[Any]) -> None:
        """
        Update telemetry feed with new packets.
        Maintains a maximum of 100 most recent packets.
        """
        self.telemetry_feed.extend(packets)
        
        # Keep only the last 100 packets
        if len(self.telemetry_feed) > 100:
            self.telemetry_feed = self.telemetry_feed[-100:]

    def on_alert_received(self, alert: ThreatAlert | Any) -> None:
        """
        Handle incoming threat alert.
        Delegates to AlertDisplay for queue management.
        """
        self.alert_display.enqueue_alert(alert)

    def issue_override(self, command: Any) -> None:
        """
        Issue an operator override command.
        Publishes command via CommunicationBus and logs incident.
        """
        if isinstance(command, dict):
            payload = dict(command)
            payload.setdefault("target", "ALL")
            if "command" not in payload:
                payload["command"] = str(command)
        else:
            payload = {
                "command": str(command),
                "target": "ALL",
            }

        try:
            from atlas_communication.communication_bus import CommunicationBus
            from atlas_common import MessageType
            
            bus = CommunicationBus.get_instance()
            bus.publish(MessageType.OPERATOR_COMMAND, payload)
            bus.dispatch()
            
            print(f"Operator override issued: {payload}")
            
        except ImportError:
            print("WARNING: CommunicationBus not available, command not sent")
        except Exception as e:
            print(f"ERROR: Failed to issue override: {e}")
        
        # Log the override as an incident
        try:
            from atlas_data import DataLogger
            from atlas_common import IncidentType
            
            logger = DataLogger.get_instance()
            logger.log_incident(
                incident_type=IncidentType.GEOFENCE_VIOLATION,  # Representative type for override
                uav_id="OPERATOR",
                details=f"Operator override command issued: {payload}",
            )
        except Exception as e:
            print(f"WARNING: Could not log incident: {e}")

    def abort_mission(self) -> None:
        """
        Abort the current mission.
        Delegates to MissionController.
        """
        self.mission_controller.abort_mission()

    def _on_telemetry(self, packet: Any) -> None:
        """
        Internal callback for telemetry messages.
        Updates telemetry feed.
        """
        self.display_swarm_status([packet])

    def _on_world_state(self, state: Any) -> None:
        """
        Internal callback for world state messages.
        Can be extended for world state processing.
        """
        # Placeholder for world state handling
        pass
