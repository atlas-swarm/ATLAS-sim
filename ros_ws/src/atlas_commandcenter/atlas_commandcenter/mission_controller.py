from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_common import MessageType, GeoCoordinate, IncidentType, MissionStatus
from atlas_data import MissionPlan

if TYPE_CHECKING:
    from atlas_communication.communication_bus import CommunicationBus


@dataclass
class MissionController:
    """
    Command pattern implementation for mission control.
    Manages mission lifecycle and waypoint navigation.
    """
    
    active_plan: MissionPlan | None = None
    patrol_boundary: list[GeoCoordinate] = field(default_factory=list)
    waypoint_index: int = 0
    status: MissionStatus = MissionStatus.IDLE

    def validate_plan(self, plan: MissionPlan) -> bool:
        """
        Validate mission plan.
        Returns True if waypoints is not empty AND patrol_boundary has at least 3 points.
        Returns False otherwise and logs error.
        """
        if not plan.waypoints:
            print("ERROR: Mission plan has no waypoints")
            return False
        
        if len(plan.patrol_boundary) < 3:
            print("ERROR: Patrol boundary must have at least 3 points")
            return False
        
        return True

    def start_mission(self, plan: MissionPlan) -> None:
        """
        Start mission execution.
        Validates plan, sets status to RUNNING, and sends NAVIGATE command to UAVs.
        """
        if not self.validate_plan(plan):
            print("ERROR: Cannot start mission - validation failed")
            return
        
        self.status = MissionStatus.RUNNING
        self.active_plan = plan
        self.waypoint_index = 0
        self.patrol_boundary = plan.patrol_boundary
        
        # Send NAVIGATE command to UAVs via CommunicationBus
        try:
            from atlas_communication.communication_bus import CommunicationBus
            bus = CommunicationBus.get_instance()
            # Publish NAVIGATE command with first waypoint
            bus.publish(MessageType.SWARM_COMMAND, {
                "command": "NAVIGATE",
                "waypoint_index": 0,
                "waypoint": plan.waypoints[0] if plan.waypoints else None,
            })
            bus.dispatch()
        except ImportError:
            # CommunicationBus not available yet - graceful degradation
            print("WARNING: CommunicationBus not available, command not sent")

    def pause_mission(self) -> None:
        """
        Pause mission execution.
        Sets status to PAUSED and sends HOVER command to UAVs.
        """
        self.status = MissionStatus.PAUSED
        
        # Send HOVER command to UAVs
        try:
            from atlas_communication.communication_bus import CommunicationBus
            bus = CommunicationBus.get_instance()
            bus.publish(MessageType.SWARM_COMMAND, {
                "command": "HOVER",
            })
            bus.dispatch()
        except ImportError:
            # CommunicationBus not available yet - graceful degradation
            print("WARNING: CommunicationBus not available, command not sent")

    def resume_mission(self) -> None:
        """
        Resume paused mission.
        Sets status to RUNNING and sends continue command to UAVs.
        """
        self.status = MissionStatus.RUNNING
        
        # Send continue command to UAVs
        try:
            from atlas_communication.communication_bus import CommunicationBus
            bus = CommunicationBus.get_instance()
            bus.publish(MessageType.SWARM_COMMAND, {
                "command": "CONTINUE",
                "waypoint_index": self.waypoint_index,
            })
            bus.dispatch()
        except ImportError:
            # CommunicationBus not available yet - graceful degradation
            print("WARNING: CommunicationBus not available, command not sent")

    def abort_mission(self) -> None:
        """
        Abort mission execution.
        Sets status to ABORTED, sends RTL command to UAVs, and logs incident.
        """
        self.status = MissionStatus.ABORTED
        
        # Send RTL (Return To Launch) command to UAVs
        try:
            from atlas_communication.communication_bus import CommunicationBus
            bus = CommunicationBus.get_instance()
            bus.publish(MessageType.SWARM_COMMAND, {
                "command": "RTL",
            })
            bus.dispatch()
        except ImportError:
            # CommunicationBus not available yet - graceful degradation
            print("WARNING: CommunicationBus not available, command not sent")
        
        # Log incident to DataLogger
        try:
            from atlas_data import DataLogger
            logger = DataLogger.get_instance()
            logger.log_incident(
                incident_type=IncidentType.MISSION_ABORT,
                uav_id="ALL",
                details="Mission aborted by operator",
            )
        except Exception as e:
            print(f"WARNING: Could not log incident: {e}")

    def update_waypoint(self, index: int, coord: GeoCoordinate) -> None:
        """
        Update a waypoint coordinate in the active mission plan.
        """
        if self.active_plan is None:
            print("ERROR: No active mission plan")
            return
        
        if index < 0 or index >= len(self.active_plan.waypoints):
            print(f"ERROR: Invalid waypoint index {index}")
            return
        
        self.active_plan.waypoints[index].coordinate = coord

    def get_status(self) -> MissionStatus:
        """Get current mission status."""
        return self.status

    def on_waypoint_reached(self, uav_id: int, waypoint_index: int) -> None:
        """
        Handle waypoint reached event.
        Increments waypoint_index. If all waypoints completed, sets status to COMPLETED.
        """
        if self.active_plan is None:
            return
        
        # Update waypoint index
        self.waypoint_index = waypoint_index + 1
        
        # Check if all waypoints have been completed
        if self.waypoint_index >= len(self.active_plan.waypoints):
            self.status = MissionStatus.COMPLETED
            print(f"Mission completed - all waypoints reached by UAV {uav_id}")
