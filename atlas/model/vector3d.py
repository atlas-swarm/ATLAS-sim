"""3-D Euclidean vector for velocity, acceleration, and direction."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Vector3D:
    """Immutable three-dimensional vector."""

    x: float
    y: float
    z: float

    def magnitude(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def normalized(self) -> Vector3D:
        """Return unit vector; raises ZeroDivisionError for zero vector."""
        mag = self.magnitude()
        return Vector3D(self.x / mag, self.y / mag, self.z / mag)

    def __add__(self, other: Vector3D) -> Vector3D:
        return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3D) -> Vector3D:
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3D:
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)
