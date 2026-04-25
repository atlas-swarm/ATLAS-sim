from dataclasses import dataclass
from typing import Dict

from atlas_common import GeoCoordinate, WeatherState
from atlas_threat.sensor_simulator import CameraFrame, SensorSimulator, ThermalFrame


@dataclass
class UAVState:
    uav_id: int
    position: GeoCoordinate
    heading: float  # derece, 0–360


@dataclass
class TickFrames:
    uav_id: int
    camera: CameraFrame
    thermal: ThermalFrame


class SimEngineStub:
    """Ege'nin SimulationEngine'i hazır olana kadar kullanılacak mock.

    Her tick() çağrısında:
      1. Mevcut weatherState SensorSimulator'a uygulanır (dinamik degradation).
      2. Kayıtlı tüm UAV'ların o anki position ve heading değerleriyle
         get_camera_data() ve get_thermal_data() çağrılır.
      3. Sonuçlar {uav_id: TickFrames} dict olarak döndürülür.

    Gerçek SimulationEngine geldiğinde:
      - register_uav / update_uav_state → SimEngine'in UAV listesinden okunacak
      - set_weather → SimEngine'in weatherState property'sine bağlanacak
      - tick() → SimEngine.on_tick callback'i olarak wired edilecek
    """

    def __init__(self):
        self.tick_count: int = 0
        self.weather_state: WeatherState = WeatherState.CLEAR
        self._uav_states: Dict[int, UAVState] = {}
        self._sensor_simulator: SensorSimulator = SensorSimulator()

    # ------------------------------------------------------------------
    # UAV yönetimi
    # ------------------------------------------------------------------

    def register_uav(self, uav_id: int, position: GeoCoordinate, heading: float):
        """UAV'ı simülasyona kaydet."""
        self._uav_states[uav_id] = UAVState(uav_id=uav_id, position=position, heading=heading)

    def update_uav_state(self, uav_id: int, position: GeoCoordinate, heading: float):
        """UAV'ın mevcut konum ve yön bilgisini güncelle (her hareketten sonra çağır)."""
        if uav_id in self._uav_states:
            self._uav_states[uav_id].position = position
            self._uav_states[uav_id].heading = heading

    # ------------------------------------------------------------------
    # Hava durumu
    # ------------------------------------------------------------------

    def set_weather(self, weather: WeatherState):
        """Hava durumunu değiştir; bir sonraki tick'te sensor degradation yansır."""
        self.weather_state = weather

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self) -> Dict[int, TickFrames]:
        """Bir simülasyon adımını işle.

        Her tick'te:
        - weatherState dinamik olarak SensorSimulator'a uygulanır
        - Tüm UAV'lar için o anki position/heading ile sensor frame'leri üretilir

        Returns:
            {uav_id: TickFrames} — kamera ve termal veriler
        """
        self.tick_count += 1
        self._sensor_simulator.apply_weather_degradation(self.weather_state)

        frames: Dict[int, TickFrames] = {}
        for uav_id, state in self._uav_states.items():
            camera = self._sensor_simulator.get_camera_data(
                uav_id=uav_id,
                lat=state.position.latitude,
                lon=state.position.longitude,
                heading=state.heading,
            )
            thermal = self._sensor_simulator.get_thermal_data(
                uav_id=uav_id,
                lat=state.position.latitude,
                lon=state.position.longitude,
            )
            frames[uav_id] = TickFrames(uav_id=uav_id, camera=camera, thermal=thermal)

        return frames
