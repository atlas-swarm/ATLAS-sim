"""Top-level UAV agent coordinating navigation, avoidance, and emergency handling."""

from dataclasses import dataclass, field

from atlas_common.enums import FlightMode, MissionStatus
from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_uav.collision_avoider import CollisionAvoider
from atlas_uav.emergency_handler import EmergencyHandler
from atlas_uav.navigation_controller import NavigationController


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

    def tick(self, obstacles: list[GeoCoordinate]) -> None:
        """Execute one control cycle: check emergencies, avoidance, navigation."""
        recommended = self.emergency.recommend_mode(self.battery_pct)
        if recommended in (FlightMode.RTL, FlightMode.LAND):
            self.flight_mode = recommended
            return

        correction = self.avoider.evaluate(self.position, self.velocity, obstacles)
        if correction is not None:
            self.velocity = correction
            self.flight_mode = FlightMode.HOVER
            return

        if self.navigation.has_reached(self.position):
            advanced = self.navigation.advance()
            if not advanced:
                self.mission_status = MissionStatus.COMPLETED
                self.flight_mode = FlightMode.HOVER

    def abort(self) -> None:
        """Immediately cancel the mission and enter RTL."""
        self.mission_status = MissionStatus.ABORTED
        self.flight_mode = FlightMode.RTL
