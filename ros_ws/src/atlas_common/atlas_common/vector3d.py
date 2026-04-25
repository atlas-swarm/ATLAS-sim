from dataclasses import dataclass


@dataclass(slots=True)
class Vector3D:
    x: float
    y: float
    z: float = 0.0