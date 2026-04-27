"""ATLAS Demo Script — Hafta 4

Senaryo:
  1. 3 UAV V_SHAPE formasyonunda rectangular boundary'de devriye geze.
  2. Tehdit algılandığında FormationManager V_SHAPE → GRID'e geçsin.
  3. ~30. tick'te UAV-1'in battery'si 0'a düşsün (simulate_uav_loss).
  4. SwarmCoordinator redistribute_zones() çalışsın, kalan 2 UAV'a
     yeni zone waypoint'leri gönderilsin — demo'da izlenebilir olsun.

Kullanım:
    python demo_script.py
"""

from __future__ import annotations

import time

from atlas_common.enums import FlightMode, FormationType
from atlas_common.geo_coordinate import GeoCoordinate
from atlas_common.vector3d import Vector3D
from atlas_simulation.models import SimConfig, SimObject
from atlas_simulation.simulation_engine import SimulationEngine
from atlas_uav.uav_agent import UAVAgent
from atlas_uav.navigation_controller import NavigationController
from atlas_uav.collision_avoider import CollisionAvoider
from atlas_uav.emergency_handler import EmergencyHandler
from atlas_swarm.formation_manager import FormationManager
from atlas_swarm.swarm_coordinator import SwarmCoordinator
from atlas_swarm.models import Waypoint
from atlas_threat.threat_detector import ThreatDetector

try:
    from atlas_uav.strategy.simple_avoidance import SimpleAvoidanceStrategy
    _strategy_factory = SimpleAvoidanceStrategy
except ImportError:
    from atlas_uav.strategy.i_avoidance_strategy import IAvoidanceStrategy
    from atlas_common.vector3d import Vector3D as _V3

    class _StubStrategy(IAvoidanceStrategy):  # type: ignore[misc]
        def is_threat(self, pos, obs):
            dlat = (pos.latitude - obs.latitude) * 111_320
            dlon = (pos.longitude - obs.longitude) * 111_320
            return (dlat**2 + dlon**2) ** 0.5 < 15.0

        def compute_avoidance_vector(self, pos, obs, vel):
            dlat = pos.latitude - obs.latitude
            dlon = pos.longitude - obs.longitude
            mag = max((dlat**2 + dlon**2) ** 0.5, 1e-9)
            return _V3(dlat / mag * 0.0001, dlon / mag * 0.0001, 0.0)

    _strategy_factory = _StubStrategy


TICK_INTERVAL_MS = 100
TOTAL_TICKS = 80
UAV_LOSS_TICK = 30
THREAT_TICK = 15

BOUNDARY = [
    GeoCoordinate(latitude=39.90, longitude=32.85),
    GeoCoordinate(latitude=39.91, longitude=32.85),
    GeoCoordinate(latitude=39.91, longitude=32.87),
    GeoCoordinate(latitude=39.90, longitude=32.87),
]

WAYPOINTS = [
    Waypoint(coordinate=GeoCoordinate(39.900, 32.850), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.905, 32.855), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.910, 32.860), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.910, 32.865), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.905, 32.865), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.900, 32.865), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.900, 32.860), altitude=100.0),
    Waypoint(coordinate=GeoCoordinate(39.900, 32.855), altitude=100.0),
]
for i, wp in enumerate(WAYPOINTS):
    wp.sequence = i

THREAT_OBJECT = SimObject(
    object_id="threat-001",
    position=GeoCoordinate(latitude=39.902, longitude=32.853, altitude=0.0),
    radius_m=5.0,
    metadata={"type": "VEHICLE"},
)


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _make_uav(uav_id: str, start_lat: float, start_lon: float) -> UAVAgent:
    nav = NavigationController(uav_id=uav_id)
    nav.load_route(list(WAYPOINTS))
    avoider = CollisionAvoider(uav_id=uav_id, strategy=_strategy_factory())
    emergency = EmergencyHandler(uav_id=uav_id)
    return UAVAgent(
        uav_id=uav_id,
        navigation=nav,
        avoider=avoider,
        emergency=emergency,
        position=GeoCoordinate(latitude=start_lat, longitude=start_lon, altitude=100.0),
        velocity=Vector3D(0.0, 0.0, 0.0),
        flight_mode=FlightMode.PATROL,
        battery_pct=100.0,
    )


def setup() -> tuple[SimulationEngine, SwarmCoordinator, list[UAVAgent]]:
    _log("=== ATLAS Demo Kurulumu ===")

    engine = SimulationEngine.get_instance()
    config = SimConfig(
        tick_interval_ms=TICK_INTERVAL_MS,
        patrol_boundary=BOUNDARY,
        initial_sim_objects=[],
    )
    engine.initialize(config)

    spacing_deg = 30.0 / 111_320.0
    uav0 = _make_uav("0", 39.900, 32.850)
    uav1 = _make_uav("1", 39.900 - spacing_deg, 32.850 + spacing_deg)
    uav2 = _make_uav("2", 39.900 - spacing_deg, 32.850 - spacing_deg)
    agents = [uav0, uav1, uav2]

    for agent in agents:
        engine.register_uav(agent)

    for agent in agents:
        td = ThreatDetector(uav_id=int(agent.uav_id))
        engine.register_threat_detector(td, uav_id=int(agent.uav_id))

    fm = FormationManager(formation_type=FormationType.V_SHAPE, formation_spacing=30.0)
    coordinator = SwarmCoordinator(formation_manager=fm)
    coordinator.assign_zones(agents, BOUNDARY)

    for agent in agents:
        agent.emergency.on_uav_lost = coordinator.handle_uav_lost

    _log(f"  Başlangıç formasyonu: {fm.formation_type.value}")
    _log(f"  UAV'lar: {[a.uav_id for a in agents]}")
    _log(f"  Zone dağılımı: {list(coordinator.get_coverage_map().keys())}")

    return engine, coordinator, agents


def run_demo() -> None:
    engine, coordinator, agents = setup()
    _log("\n=== Demo Başlıyor ===\n")

    for tick in range(1, TOTAL_TICKS + 1):

        if tick == THREAT_TICK:
            _log(f"[Tick {tick:03d}] *** Tehdit nesnesi patrol alanına ekleniyor ***")
            engine.environment.add_threat_object(THREAT_OBJECT)

        if tick == UAV_LOSS_TICK:
            _log(f"[Tick {tick:03d}] *** UAV-1 kaybı simüle ediliyor (battery=0) ***")
            coordinator.simulate_uav_loss("1")

        world_state = engine.run_cycle()

        if tick % 5 == 0 or tick in (THREAT_TICK, THREAT_TICK + 1, UAV_LOSS_TICK, UAV_LOSS_TICK + 1):
            _log(f"[Tick {tick:03d}] Formasyon: {coordinator.formation_manager.formation_type.value}")
            for agent in agents:
                pos = agent.position
                _log(
                    f"          UAV-{agent.uav_id}: "
                    f"lat={pos.latitude:.6f} lon={pos.longitude:.6f} "
                    f"bat={agent.battery_pct:.1f}% "
                    f"mode={agent.flight_mode.value}"
                )
            active_ids = [a.uav_id for a in coordinator._agents]
            _log(f"          Aktif swarm: {active_ids} | Zones: {list(coordinator.get_coverage_map().keys())}")

        if world_state.active_alerts:
            for alert in world_state.active_alerts:
                _log(f"[Tick {tick:03d}] THREAT ALERT: {alert}")

        time.sleep(TICK_INTERVAL_MS / 1000.0)

    _log("\n=== Demo Tamamlandı ===")
    engine.stop()


if __name__ == "__main__":
    run_demo()
