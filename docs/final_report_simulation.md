# Final Report - Simulation Section

## Implementation Decisions

### SimulationEngine

SimulationEngine tek tick sahibi olacak şekilde singleton tutuldu. `run_cycle()` akışı RLock ile serileştiriliyor; böylece arka plan loop'u, manuel `tick()` çağrısı, start/stop ve registry güncellemeleri aynı anda state'i bozacak biçimde ilerlemiyor.

Tick artık resilient çalışır: UAV update, state collection, PhysicsProcessor, geofence recovery, ThreatDetector, telemetry builder, DataLogger ve CommunicationBus hataları `SUBSYSTEM_ERROR` event'i olarak kaydedilir; tick çökmek yerine kalan alt sistemlerle devam eder. `last_tick_duration_ms` ve `max_tick_duration_ms` alanları performans son kontrolü için her tick sonunda güncellenir.

### EnvironmentModel

EnvironmentModel patrol boundary, weather ve sim object listesini SimulationEngine'den ayrı tutar. Boundary en az üç koordinatla doğrulanır; sim object kayıtları `object_id` üzerinden replace edilebilir. ThreatDetector entegrasyonu için sim object'ler tick sırasında izole dict payload'larına dönüştürülür; bozuk object verisi tick'i düşürmez, error event'e çevrilir.

### PhysicsProcessor

PhysicsProcessor basit lineer hareket modeliyle UAV konumlarını `velocity * delta_time` üzerinden ilerletir. Boundary dışına çıkan UAV'ler son geçerli pozisyona clamp edilir, yatay hızları sıfırlanır ve `GEOFENCE_VIOLATION` event'i üretir. SimulationEngine bu event'i işlerken UAV'yi hover moduna alır; hover hook'u hata verirse yalnızca recovery error event'i kaydedilir.

## Tick Loop Architecture

```text
SimulationEngine.run_cycle()
  1. Tick state reset + current_tick increment
  2. UAVAgent.update()/tick()
  3. UAVState collection from registered agents
  4. PhysicsProcessor.update_positions()
  5. Geofence recovery through hover hooks
  6. UAV state sync back to agents
  7. ThreatDetector.update()
  8. Telemetry packet build
  9. WorldState snapshot copy
 10. CommunicationBus telemetry publish
 11. DataLogger telemetry/event writes
 12. CommunicationBus world-state publish + dispatch
 13. Periodic DataLogger flush
 14. Mission completion check/stop
```

## Subsystem Connection Order

| Order | Integration point | Connected behavior |
| --- | --- | --- |
| 1 | MissionController | `startMission()`/`start_mission()` loads mission waypoints and boundary. |
| 2 | UAVAgent | `update()` or `tick()` runs before physics. |
| 3 | NavigationController | `navigation.load_route()` receives normalized waypoint adapters. |
| 4 | EnvironmentModel | Patrol boundary and sim objects feed physics and threat detection. |
| 5 | PhysicsProcessor | Advances positions and emits geofence events. |
| 6 | ThreatDetector | Runs after physics/state sync against current sim objects. |
| 7 | CommunicationBus + DataLogger | Publishes telemetry/world/emergency payloads and records telemetry/events without blocking the tick. |

EmergencyHandler is connected through `triggerRTL()`/`trigger_rtl()`: the engine switches the UAV to RTL, calls `agent.emergency.report_fault()` when available, logs an `EMERGENCY_EVENT`, and publishes it through the same resilient bus path.

## Demo Config

`ros_ws/src/atlas_simulation/missions/mission_demo.json` is the active demo mission:

- 3 UAVs
- rectangular 4-point boundary
- 8 waypoint patrol route
- 1 central threat sim object
- `tickIntervalMs`: 80
- `detectionRadius`: 170.0
- `formationSpacing`: 18.0

The standalone demo summary reports mission status, counts, log paths, threat detection result, and average/max tick duration. The 10-UAV performance smoke test asserts `max_tick_duration_ms < tick_interval_ms`.
