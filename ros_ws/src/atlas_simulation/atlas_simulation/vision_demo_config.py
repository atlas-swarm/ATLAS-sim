from __future__ import annotations

from environment_model import EnvironmentModel
from models import GeoCoordinate

DEMO_RESTRICTED_ZONE: list[GeoCoordinate] = [
    GeoCoordinate(latitude=39.9100, longitude=32.8000, altitude=0.0),
    GeoCoordinate(latitude=39.9100, longitude=32.8050, altitude=0.0),
    GeoCoordinate(latitude=39.9060, longitude=32.8050, altitude=0.0),
    GeoCoordinate(latitude=39.9060, longitude=32.8000, altitude=0.0),
]

DEMO_CAMERA_RESOLUTION: tuple[int, int] = (640, 480)

DEMO_CONFIDENCE_THRESHOLD: float = 0.4


def build_demo_environment() -> EnvironmentModel:
    env = EnvironmentModel()
    env.set_restricted_zone(DEMO_RESTRICTED_ZONE)
    return env


def get_performance_targets() -> dict:
    return {
        "max_vision_tick_ms": 100,
        "min_detection_confidence": 0.4,
        "max_false_positive_rate": 0.05,
        "target_fps": 10,
    }


if __name__ == "__main__":
    env = build_demo_environment()
    print(f"Restricted zone vertex count: {len(env.restricted_zone)}")
    for i, coord in enumerate(env.restricted_zone):
        print(f"  [{i}] lat={coord.latitude}, lon={coord.longitude}")
    print(f"Camera resolution: {DEMO_CAMERA_RESOLUTION}")
    print(f"Confidence threshold: {DEMO_CONFIDENCE_THRESHOLD}")
    print(f"Performance targets: {get_performance_targets()}")
