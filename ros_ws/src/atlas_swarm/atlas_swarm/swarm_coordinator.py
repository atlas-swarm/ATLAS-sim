"""Swarm-level coordination: zone assignment, formation changes, UAV loss handling.

Hafta 4 değişiklikleri (4.2.3):
  - simulate_uav_loss(): battery=0 set eder, EmergencyHandler callback'ini bağlar.
  - handle_uav_lost(): demo'da izlenebilir adım adım log üretir.
  - redistribute_zones(): kalan UAV'lara yeni zone merkezini waypoint olarak gönderir.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from atlas_common.geo_coordinate import GeoCoordinate
from atlas_swarm.formation_manager import FormationManager
from atlas_swarm.models import (
    PatrolZone,
    SwarmMessage,
    SwarmMessageType,
    UAVCommand,
    UAVCommandType,
    Waypoint,
)

if TYPE_CHECKING:
    from atlas_threat.threat_alert import ThreatAlert
    from atlas_uav.uav_agent import UAVAgent


@dataclass
class SwarmCoordinator:
    formation_manager: FormationManager = field(default_factory=FormationManager)
    coverage_zones: list[PatrolZone] = field(default_factory=list)
    active_alerts: list[ThreatAlert] = field(default_factory=list)

    def __post_init__(self):
        self._agents: list[UAVAgent] = []
        from atlas_communication.communication_bus import CommunicationBus, MessageType
        CommunicationBus.get_instance().subscribe(
            MessageType.OPERATOR_COMMAND, self.handle_operator_command
        )

    def assign_zones(self, agents: list[UAVAgent], boundary: list[GeoCoordinate]) -> None:
        self._agents = agents
        if not agents or not boundary:
            return
        lats = [c.latitude for c in boundary]
        lons = [c.longitude for c in boundary]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        n = len(agents)
        lon_step = (max_lon - min_lon) / n
        self.coverage_zones = []
        for i, agent in enumerate(agents):
            lon_start = min_lon + i * lon_step
            lon_end = lon_start + lon_step
            self.coverage_zones.append(PatrolZone(
                assigned_uav_id=int(agent.uav_id),
                boundary=[
                    GeoCoordinate(latitude=min_lat, longitude=lon_start),
                    GeoCoordinate(latitude=max_lat, longitude=lon_start),
                    GeoCoordinate(latitude=max_lat, longitude=lon_end),
                    GeoCoordinate(latitude=min_lat, longitude=lon_end),
                ],
            ))

    def get_coverage_map(self) -> dict[int, PatrolZone]:
        return {zone.assigned_uav_id: zone for zone in self.coverage_zones}

    def on_threat_detected(self, alert: ThreatAlert) -> None:
        self.active_alerts.append(alert)
        self.formation_manager.adapt_formation(alert)
        self.broadcast_to_swarm(SwarmMessage(
            sender_id=-1,
            type=SwarmMessageType.FORMATION_CHANGE,
            payload={"reason": "THREAT_DETECTED", "alert_id": str(alert.alert_id)},
        ))

    # ------------------------------------------------------------------ #
    #  UAV kaybı (4.2.3)                                                  #
    # ------------------------------------------------------------------ #

    def simulate_uav_loss(self, uav_id: str) -> None:
        """Demo'da bir UAV'ı devre dışı bırakır: battery=0 set edilir."""
        for agent in self._agents:
            if agent.uav_id == uav_id:
                agent.battery_pct = 0.0
                if agent.emergency.on_uav_lost is None:
                    agent.emergency.on_uav_lost = self.handle_uav_lost
                _log(f"[SwarmCoordinator] UAV {uav_id} battery=0 → loss simulated")
                return
        _log(f"[SwarmCoordinator] simulate_uav_loss: UAV {uav_id} not found")

    def handle_uav_lost(self, uav_id: str) -> None:
        """EmergencyHandler callback'i tarafından çağrılır."""
        _log(f"[SwarmCoordinator] *** UAV LOST: {uav_id} ***")
        _log(f"[SwarmCoordinator] Active before: {[a.uav_id for a in self._agents]}")
        self._agents = [a for a in self._agents if a.uav_id != uav_id]
        _log(f"[SwarmCoordinator] Active after:  {[a.uav_id for a in self._agents]}")
        try:
            self.redistribute_zones(int(uav_id))
        except (ValueError, TypeError):
            _log(f"[SwarmCoordinator] Cannot parse uav_id={uav_id!r}, skip redistribution")

    def redistribute_zones(self, failed_uav_id: int) -> None:
        """Redistribute patrol zones after a UAV is lost."""
        _log(f"[SwarmCoordinator] Redistributing zones (failed: UAV {failed_uav_id})")

        failed_zone = next(
            (z for z in self.coverage_zones if z.assigned_uav_id == failed_uav_id), None
        )
        if failed_zone is None:
            _log(f"[SwarmCoordinator] No zone for UAV {failed_uav_id}, nothing to do")
            return

        remaining = [z for z in self.coverage_zones if z.assigned_uav_id != failed_uav_id]
        if not remaining:
            self.coverage_zones = []
            _log("[SwarmCoordinator] No remaining UAVs — coverage cleared")
            return

        all_lons = [pt.longitude for zone in [failed_zone, *remaining] for pt in zone.boundary]
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
            center_lat = (min_lat + max_lat) / 2
            center_lon = (lon_start + lon_end) / 2
            _log(f"[SwarmCoordinator]   UAV {zone.assigned_uav_id} → center ({center_lat:.6f}, {center_lon:.6f})")

        self.coverage_zones = remaining
        self._dispatch_zone_waypoints(remaining)
        self.broadcast_to_swarm(SwarmMessage(
            sender_id=-1,
            type=SwarmMessageType.ZONE_UPDATE,
            payload={"reason": f"UAV {failed_uav_id} lost", "remaining": n},
        ))
        _log(f"[SwarmCoordinator] Redistribution done — {n} UAV(s) active")

    def _dispatch_zone_waypoints(self, zones: list[PatrolZone]) -> None:
        """Send each remaining agent to the centre of its new patrol zone."""
        zone_map = {z.assigned_uav_id: z for z in zones}
        for agent in self._agents:
            try:
                int_id = int(agent.uav_id)
            except (ValueError, TypeError):
                continue
            zone = zone_map.get(int_id)
            if zone is None or len(zone.boundary) < 4:
                continue
            lats = [pt.latitude for pt in zone.boundary]
            lons = [pt.longitude for pt in zone.boundary]
            center = GeoCoordinate(
                latitude=sum(lats) / len(lats),
                longitude=sum(lons) / len(lons),
                altitude=agent.position.altitude,
            )
            cmd = UAVCommand(
                type=UAVCommandType.NAVIGATE,
                payload={"waypoints": [Waypoint(coordinate=center, altitude=agent.position.altitude)]},
                target_uav_id=agent.uav_id,
            )
            agent.receive_command(cmd)
            _log(f"[SwarmCoordinator]   NAVIGATE → UAV {agent.uav_id} ({center.latitude:.6f}, {center.longitude:.6f})")

    def map_swarm_to_uav_command(self, msg: SwarmMessage) -> UAVCommand:
        _MAP: dict[SwarmMessageType, UAVCommandType] = {
            SwarmMessageType.NAVIGATE:         UAVCommandType.NAVIGATE,
            SwarmMessageType.HOVER:            UAVCommandType.HOVER,
            SwarmMessageType.CONTINUE:         UAVCommandType.CONTINUE,
            SwarmMessageType.RTL:              UAVCommandType.RTL,
            SwarmMessageType.SET_MODE:         UAVCommandType.SET_MODE,
            SwarmMessageType.EMERGENCY:        UAVCommandType.EMERGENCY,
            SwarmMessageType.ZONE_UPDATE:      UAVCommandType.CONTINUE,
            SwarmMessageType.FORMATION_CHANGE: UAVCommandType.SET_MODE,
            SwarmMessageType.BROADCAST:        UAVCommandType.HOVER,
        }
        cmd_type = _MAP.get(msg.type, UAVCommandType.HOVER)
        payload: dict[str, Any] = dict(msg.payload) if isinstance(msg.payload, dict) else {}
        if cmd_type == UAVCommandType.NAVIGATE:
            payload = self._normalise_waypoints(payload)
        if cmd_type == UAVCommandType.SET_MODE and "mode" not in payload:
            payload["mode"] = "FORMATION"
        payload["target_uav_id"] = msg.target_uav_id
        return UAVCommand(type=cmd_type, payload=payload, target_uav_id=msg.target_uav_id)

    def broadcast_to_swarm(self, msg: SwarmMessage) -> None:
        cmd = self.map_swarm_to_uav_command(msg)
        for agent in self._agents:
            if msg.target_uav_id is None or agent.uav_id == msg.target_uav_id:
                agent.receive_command(cmd)
        from atlas_communication.communication_bus import CommunicationBus, Message, MessageType
        CommunicationBus.get_instance().publish(Message(MessageType.SWARM_COMMAND, msg))

    def handle_operator_command(self, payload: dict) -> None:
        cmd_type_str = payload.get("command_type")
        try:
            cmd_type = UAVCommandType(cmd_type_str)
        except (ValueError, TypeError):
            return
        target = payload.get("target_uav_id")
        cmd_payload = {k: v for k, v in payload.items() if k not in ("command_type", "target_uav_id")}
        cmd_payload["operator_override"] = True
        if cmd_type == UAVCommandType.NAVIGATE:
            cmd_payload = self._normalise_waypoints(cmd_payload)
        cmd = UAVCommand(type=cmd_type, payload=cmd_payload, target_uav_id=target)
        for agent in self._agents:
            if target is None or agent.uav_id == target:
                agent.receive_command(cmd)

    @staticmethod
    def _normalise_waypoints(payload: dict) -> dict:
        raw = payload.get("waypoints", [])
        normalised: list[Waypoint] = []
        for item in raw:
            if isinstance(item, Waypoint):
                normalised.append(item)
            elif isinstance(item, dict):
                try:
                    normalised.append(Waypoint.from_dict(item))
                except (KeyError, ValueError):
                    continue
        payload = dict(payload)
        payload["waypoints"] = normalised
        return payload


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
