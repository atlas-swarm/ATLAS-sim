"""Coordinates zone assignment, threat response, and swarm-wide broadcasts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_swarm.formation_manager import FormationManager
from atlas_swarm.models import PatrolZone, SwarmMessage, UAVCommand, UAVCommandType
from atlas_threat.threat_alert import ThreatAlert

if TYPE_CHECKING:
    from atlas_uav.uav_agent import UAVAgent


@dataclass
class SwarmCoordinator:
    """Manages zone coverage, threat responses, and formation coordination."""

    formation_manager: FormationManager = field(default_factory=FormationManager)
    coverage_zones: list[PatrolZone] = field(default_factory=list)
    active_alerts: list[ThreatAlert] = field(default_factory=list)
    _bound_command_bus: object | None = field(default=None, init=False, repr=False)
    _bound_command_listener: object | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ #
    #  Zone assignment                                                     #
    # ------------------------------------------------------------------ #

    def assign_zones(
        self, agents: list[UAVAgent], boundary: list[GeoCoordinate]
    ) -> None:
        """Divide *boundary* bounding box into N equal longitudinal strips.

        Each strip is assigned as a PatrolZone to the corresponding agent.
        """
        if not agents or not boundary:
            return

        lats = [c.latitude for c in boundary]
        lons = [c.longitude for c in boundary]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        n = len(agents)
        lon_step = (max_lon - min_lon) / n

        self.coverage_zones = []
        for i, _ in enumerate(agents):
            lon_start = min_lon + i * lon_step
            lon_end = lon_start + lon_step
            zone_boundary = [
                GeoCoordinate(latitude=min_lat, longitude=lon_start),
                GeoCoordinate(latitude=max_lat, longitude=lon_start),
                GeoCoordinate(latitude=max_lat, longitude=lon_end),
                GeoCoordinate(latitude=min_lat, longitude=lon_end),
            ]
            self.coverage_zones.append(PatrolZone(assigned_uav_id=i, boundary=zone_boundary))

    def get_coverage_map(self) -> dict[int, PatrolZone]:
        """Return a mapping of UAV index → PatrolZone."""
        return {zone.assigned_uav_id: zone for zone in self.coverage_zones}

    # ------------------------------------------------------------------ #
    #  Threat handling                                                     #
    # ------------------------------------------------------------------ #

    def on_threat_detected(self, alert: ThreatAlert) -> None:
        """Record the alert and trigger a formation adaptation."""
        self.active_alerts.append(alert)
        self.formation_manager.adapt_formation(alert)

    # ------------------------------------------------------------------ #
    #  Zone redistribution                                                 #
    # ------------------------------------------------------------------ #

    def redistribute_zones(self, failed_uav_id: int) -> None:
        """Remove the failed UAV's zone and redistribute it among remaining agents.

        The boundary points of the failed zone are divided evenly among the
        surviving agents' zones by expanding their longitudinal extent.
        """
        failed_zone = next(
            (z for z in self.coverage_zones if z.assigned_uav_id == failed_uav_id),
            None,
        )
        if failed_zone is None:
            return

        remaining = [z for z in self.coverage_zones if z.assigned_uav_id != failed_uav_id]
        if not remaining:
            self.coverage_zones = []
            return

        # Collect all boundary lon extents and redistribute across survivors
        all_lons = [
            lon
            for zone in [failed_zone, *remaining]
            for pt in zone.boundary
            for lon in [pt.longitude]
        ]
        all_lats = [pt.latitude for zone in remaining for pt in zone.boundary]
        min_lon, max_lon = min(all_lons), max(all_lons)
        min_lat, max_lat = min(all_lats), max(all_lats)
        n = len(remaining)
        lon_step = (max_lon - min_lon) / n

        for i, zone in enumerate(remaining):
            lon_start = min_lon + i * lon_step
            lon_end = lon_start + lon_step
            zone.boundary = [
                GeoCoordinate(latitude=min_lat, longitude=lon_start),
                GeoCoordinate(latitude=max_lat, longitude=lon_start),
                GeoCoordinate(latitude=max_lat, longitude=lon_end),
                GeoCoordinate(latitude=min_lat, longitude=lon_end),
            ]

        self.coverage_zones = remaining

    # ------------------------------------------------------------------ #
    #  Swarm broadcast                                                     #
    # ------------------------------------------------------------------ #

    def broadcast_to_swarm(self, msg: SwarmMessage) -> None:
        """Publish *msg* to all swarm members via CommunicationBus as SWARM_COMMAND."""
        from atlas_communication.communication_bus import CommunicationBus
        from atlas_common import MessageType

        CommunicationBus.get_instance().publish(MessageType.SWARM_COMMAND, msg)

    def handle_swarm_command(
        self,
        payload: dict,
        agents: list[UAVAgent] | None = None,
    ) -> None:
        """Adapt command-center SWARM_COMMAND payloads into UAVCommand objects."""
        if agents is None:
            return

        command_name = str(payload.get("command", "")).upper()
        target = payload.get("target", "ALL")

        if command_name == "NAVIGATE":
            command = UAVCommand(
                type=UAVCommandType.NAVIGATE,
                payload={
                    "waypoints": [payload["waypoint"]] if payload.get("waypoint") is not None else [],
                    "waypoint_index": payload.get("waypoint_index"),
                },
            )
        elif command_name == "HOVER":
            command = UAVCommand(
                type=UAVCommandType.SET_MODE,
                payload={"mode": "HOVER"},
            )
        elif command_name == "CONTINUE":
            command = UAVCommand(
                type=UAVCommandType.SET_MODE,
                payload={"mode": "PATROL"},
            )
        elif command_name == "RTL":
            command = UAVCommand(
                type=UAVCommandType.SET_MODE,
                payload={"mode": "RTL"},
            )
        else:
            return

        if target == "ALL":
            selected_agents = agents
        elif isinstance(target, list):
            selected_agents = [agent for agent in agents if str(agent.uav_id) in {str(item) for item in target}]
        else:
            selected_agents = [agent for agent in agents if str(agent.uav_id) == str(target)]

        for agent in selected_agents:
            agent.receive_command(command)

    def bind_command_bus(self, bus=None, agents: list[UAVAgent] | None = None) -> None:
        """Bind SWARM_COMMAND bus payloads to the local swarm-command adapter."""
        from atlas_communication.communication_bus import CommunicationBus
        from atlas_common import MessageType

        if bus is None:
            bus = CommunicationBus.get_instance()

        if self._bound_command_bus is bus and self._bound_command_listener is not None:
            return

        def _listener(payload: dict) -> None:
            self.handle_swarm_command(payload, agents)

        if self._bound_command_bus is not None and self._bound_command_listener is not None:
            try:
                self._bound_command_bus.unsubscribe(
                    MessageType.SWARM_COMMAND,
                    self._bound_command_listener,
                )
            except Exception:
                pass

        bus.subscribe(MessageType.SWARM_COMMAND, _listener)
        self._bound_command_bus = bus
        self._bound_command_listener = _listener

