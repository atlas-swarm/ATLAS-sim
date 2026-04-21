from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_common import GeoCoordinate, Waypoint


@dataclass(slots=True)
class MissionPlan:
    mission_id: str
    waypoints: list[Waypoint] = field(default_factory=list)
    patrol_boundary: list[GeoCoordinate] = field(default_factory=list)
    default_altitude: float = 0.0
    return_altitude: float = 0.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionPlan":
        boundary = [
            GeoCoordinate(**coord)
            for coord in data.get("patrol_boundary", [])
        ]

        waypoints: list[Waypoint] = []
        for item in data.get("waypoints", []):
            coordinate = GeoCoordinate(**item["coordinate"])
            waypoints.append(
                Waypoint(
                    coordinate=coordinate,
                    hold_time_sec=item.get("hold_time_sec", 0.0),
                    speed_mps=item.get("speed_mps", 0.0),
                )
            )

        return cls(
            mission_id=data["mission_id"],
            waypoints=waypoints,
            patrol_boundary=boundary,
            default_altitude=data.get("default_altitude", 0.0),
            return_altitude=data.get("return_altitude", 0.0),
            created_at=data.get(
                "created_at",
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "MissionPlan":
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def load_json(cls, path: str | Path) -> "MissionPlan":
        content = Path(path).read_text(encoding="utf-8")
        return cls.from_json(content)
