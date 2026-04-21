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

    def validate(self) -> bool:
        """Validate mission plan: mission_id must not be empty and at least 1 waypoint must exist."""
        return bool(self.mission_id) and len(self.waypoints) > 0

    def to_kml(self) -> str:
        """Convert patrol boundary and waypoints to KML format (Google Earth compatible)."""
        kml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<kml xmlns="http://www.opengis.net/kml/2.2">',
            '  <Document>',
            f'    <name>Mission: {self.mission_id}</name>',
            '    <description>ATLAS Mission Plan</description>',
        ]

        # Add patrol boundary as a polygon
        if self.patrol_boundary:
            kml_lines.extend([
                '    <Placemark>',
                '      <name>Patrol Boundary</name>',
                '      <Style>',
                '        <LineStyle>',
                '          <color>ff0000ff</color>',
                '          <width>2</width>',
                '        </LineStyle>',
                '        <PolyStyle>',
                '          <color>4d0000ff</color>',
                '        </PolyStyle>',
                '      </Style>',
                '      <Polygon>',
                '        <outerBoundaryIs>',
                '          <LinearRing>',
                '            <coordinates>',
            ])
            
            for coord in self.patrol_boundary:
                kml_lines.append(f'              {coord.longitude},{coord.latitude},{coord.altitude}')
            
            # Close the polygon by repeating the first coordinate
            if self.patrol_boundary:
                first = self.patrol_boundary[0]
                kml_lines.append(f'              {first.longitude},{first.latitude},{first.altitude}')
            
            kml_lines.extend([
                '            </coordinates>',
                '          </LinearRing>',
                '        </outerBoundaryIs>',
                '      </Polygon>',
                '    </Placemark>',
            ])

        # Add waypoints as placemarks
        for idx, waypoint in enumerate(self.waypoints):
            wp_name = waypoint.waypoint_id if waypoint.waypoint_id else f"Waypoint {idx + 1}"
            coord = waypoint.coordinate
            kml_lines.extend([
                '    <Placemark>',
                f'      <name>{wp_name}</name>',
                f'      <description>Hold: {waypoint.hold_time_sec}s, Speed: {waypoint.speed_mps}m/s</description>',
                '      <Style>',
                '        <IconStyle>',
                '          <color>ff00ff00</color>',
                '          <scale>1.2</scale>',
                '        </IconStyle>',
                '      </Style>',
                '      <Point>',
                f'        <coordinates>{coord.longitude},{coord.latitude},{coord.altitude}</coordinates>',
                '      </Point>',
                '    </Placemark>',
            ])

        kml_lines.extend([
            '  </Document>',
            '</kml>',
        ])

        return '\n'.join(kml_lines)
