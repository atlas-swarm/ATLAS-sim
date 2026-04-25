from dataclasses import dataclass

from atlas_common import WeatherState


@dataclass
class CameraFrame:
    uav_id: int
    position_lat: float
    position_lon: float
    heading: float
    quality: float  # 0.0 - 1.0


@dataclass
class ThermalFrame:
    uav_id: int
    position_lat: float
    position_lon: float
    heat_signature: float
    quality: float  # 0.0 - 1.0


class SensorSimulator:
    def __init__(self):
        self.field_of_view_deg: float = 90.0
        self.noise_level: float = 0.0
        self.thermal_enabled: bool = True

    def get_camera_data(self, uav_id: int, lat: float, lon: float, heading: float) -> CameraFrame:
        quality = max(0.0, 1.0 - self.noise_level)
        return CameraFrame(
            uav_id=uav_id,
            position_lat=lat,
            position_lon=lon,
            heading=heading,
            quality=quality,
        )

    def get_thermal_data(self, uav_id: int, lat: float, lon: float) -> ThermalFrame:
        heat = 0.8 - self.noise_level
        quality = max(0.0, 1.0 - self.noise_level)
        return ThermalFrame(
            uav_id=uav_id,
            position_lat=lat,
            position_lon=lon,
            heat_signature=heat,
            quality=quality,
        )

    def apply_weather_degradation(self, weather: WeatherState):
        if weather == WeatherState.CLEAR:
            self.noise_level = 0.0
        elif weather == WeatherState.FOGGY:
            self.noise_level = 0.8
        elif weather == WeatherState.STORMY:
            self.noise_level = 0.5
