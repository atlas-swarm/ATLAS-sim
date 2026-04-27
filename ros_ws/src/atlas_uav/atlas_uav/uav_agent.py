"""Top-level UAV agent coordinating navigation, avoidance, and emergency handling.

Hafta 4 değişiklikleri:
  4.2.1 — tick() içinde NavigationController.compute_velocity() kullanılarak
           velocity sert atlamak yerine smooth interpolasyonla güncellenir.
  4.2.2 — Avoidance vektörü uygulandığında waypoint hedefi kaybolmaz:
           correction NavigationController'a iletilir, blend orada yapılır.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_common.enums import FlightMode, MissionStatus
from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_uav.collision_avoider import CollisionAvoider
from atlas_uav.emergency_handler import EmergencyHandler
from atlas_uav.navigation_controller import NavigationController

if TYPE_CHECKING:
    from atlas_swarm.models import UAVCommand

# UAV seyir hızı (m/s) — demo parametresi
_CRUISE_SPEED_MPS: float = 5.0


@dataclass
class UAVAgent:
    """Orchestrates all subsystems for a single UAV platform."""

    uav_id: str
    navigation: NavigationController
    avoider: CollisionAvoider
    emergency: EmergencyHandler
    position: GeoCoordinate = field(default_factory=lambda: GeoCoordinate(0.0, 0.0))
    velocity: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    flight_mode: FlightMode = FlightMode.HOVER
    mission_status: MissionStatus = MissionStatus.IDLE
    battery_pct: float = 100.0

    # ------------------------------------------------------------------ #
    #  Core control loop                                                   #
    # ------------------------------------------------------------------ #

    def tick(self, obstacles: list[GeoCoordinate]) -> None:
        """Execute one control cycle: emergencies → avoidance → navigation.

        4.2.2 öncelik mantığı:
          - avoidance tetiklenirse correction NavigationController'a iletilir.
          - NavigationController bunu waypoint yönüyle blend eder.
          - Bu tick'te velocity avoidance-blend sonucu olur; waypoint hedefi korunur.

        4.2.1 smooth hareket:
          - Avoidance yoksa compute_velocity() interpolated velocity döndürür.
          - Sert pozisyon atlama yok.
        """
        # 1) Emergency kontrolü — en yüksek öncelik
        recommended = self.emergency.recommend_mode(self.battery_pct)
        if recommended in (FlightMode.RTL, FlightMode.LAND):
            self.flight_mode = recommended
            self.velocity = Vector3D(0.0, 0.0, 0.0)
            return

        # 2) Collision avoidance
        correction = self.avoider.evaluate(self.position, self.velocity, obstacles)
        if correction is not None:
            # Correction NavigationController'a iletilir → blend orada yapılır
            self.navigation.set_avoidance_correction(correction)

        # 3) Navigation — smooth interpolated velocity (avoidance dahil blend)
        nav_velocity = self.navigation.compute_velocity(self.position, _CRUISE_SPEED_MPS)
        if nav_velocity is not None:
            self.velocity = nav_velocity

        # 4) Waypoint ulaşım kontrolü
        if self.navigation.has_reached(self.position):
            advanced = self.navigation.advance()
            if not advanced:
                self.mission_status = MissionStatus.COMPLETED
                self.flight_mode = FlightMode.HOVER

    def abort(self) -> None:
        """Immediately cancel the mission and enter RTL."""
        self.mission_status = MissionStatus.ABORTED
        self.flight_mode = FlightMode.RTL
        self.velocity = Vector3D(0.0, 0.0, 0.0)

    # ------------------------------------------------------------------ #
    #  Communication & command handling                                    #
    # ------------------------------------------------------------------ #

    def report_status(self) -> None:
        """Produce a TelemetryPacket snapshot and publish it as TELEMETRY."""
        from atlas_communication.communication_bus import (
            CommunicationBus,
            Message,
            MessageType,
        )
        from atlas_communication.telemetry_packet import (
            FlightMode as CommFlightMode,
            GeoCoordinate as CommGeo,
            TelemetryPacket,
            Vector3D as CommVec,
        )

        packet = TelemetryPacket(
            uav_id=int(self.uav_id),
            position=CommGeo(
                lat=self.position.latitude,
                lon=self.position.longitude,
                alt=self.position.altitude,
            ),
            velocity=CommVec(
                x=self.velocity.x,
                y=self.velocity.y,
                z=self.velocity.z,
            ),
            battery_level=self.battery_pct / 100.0,
            flight_mode=CommFlightMode(self.flight_mode.value),
            timestamp=int(time.time()),
        )
        CommunicationBus.get_instance().publish(Message(MessageType.TELEMETRY, packet))

    def receive_command(self, cmd: "UAVCommand") -> None:
        """Handle an incoming UAVCommand."""
        from atlas_swarm.models import UAVCommandType

        if cmd.type == UAVCommandType.NAVIGATE:
            waypoints = cmd.payload.get("waypoints", [])
            self.navigation.load_route(waypoints)
            self.mission_status = MissionStatus.RUNNING
            self.flight_mode = FlightMode.PATROL

        elif cmd.type == UAVCommandType.SET_MODE:
            self.flight_mode = FlightMode(cmd.payload["mode"])

        elif cmd.type == UAVCommandType.EMERGENCY:
            reason = cmd.payload.get("reason", "external emergency command")
            self.emergency.report_fault(reason)
            self.abort()

        elif cmd.type == UAVCommandType.HOVER:
            self.flight_mode = FlightMode.HOVER
            self.velocity = Vector3D(0.0, 0.0, 0.0)

        elif cmd.type == UAVCommandType.CONTINUE:
            if self.flight_mode == FlightMode.HOVER:
                self.flight_mode = FlightMode.PATROL

        elif cmd.type == UAVCommandType.RTL:
            reason = cmd.payload.get("reason", "RTL command received")
            self.emergency.report_fault(reason)
            self.flight_mode = FlightMode.RTL
            self.mission_status = MissionStatus.ABORTED
            self.velocity = Vector3D(0.0, 0.0, 0.0)

    # ------------------------------------------------------------------ #
    #  Health check                                                        #
    # ------------------------------------------------------------------ #

    def is_healthy(self) -> bool:
        """Return True if battery is above 15 % and no active faults are recorded."""
        return (self.battery_pct / 100.0) > 0.15 and not self.emergency.has_active_faults
