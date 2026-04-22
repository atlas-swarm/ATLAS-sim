"""Computes and manages geometric flight formations for the UAV swarm."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from atlas_common.enums import FormationType
from atlas_common.geo_coordinate import GeoCoordinate

if TYPE_CHECKING:
    from atlas_uav.uav_agent import UAVAgent

# 1 degree of latitude in metres (WGS-84 approximation)
_METRES_PER_DEG: float = 111_320.0


@dataclass
class FormationManager:
    """Computes target positions and assigns leadership roles within a formation."""

    formation_type: FormationType = FormationType.V_SHAPE
    lead_uav_id: int = 0
    formation_spacing: float = 30.0  # metres between adjacent UAVs

    def set_formation_type(self, formation_type: FormationType) -> None:
        """Switch to a different formation pattern."""
        self.formation_type = formation_type

    def assign_formation_roles(self, agents: list[UAVAgent]) -> None:
        """Set the UAV with the highest battery level as the formation lead."""
        if not agents:
            return
        lead = max(range(len(agents)), key=lambda i: agents[i].battery_pct)
        self.lead_uav_id = lead

    def compute_formation_positions(
        self, agents: list[UAVAgent]
    ) -> dict[int, GeoCoordinate]:
        """Return target GeoCoordinate for each agent index given the current formation.

        Positions are computed relative to the lead UAV's current location.
        """
        if not agents:
            return {}

        lead = agents[self.lead_uav_id] if self.lead_uav_id < len(agents) else agents[0]
        origin = lead.position
        spacing_deg = self.formation_spacing / _METRES_PER_DEG

        positions: dict[int, GeoCoordinate] = {}

        for i, agent in enumerate(agents):
            if i == self.lead_uav_id:
                positions[i] = GeoCoordinate(
                    latitude=origin.latitude,
                    longitude=origin.longitude,
                    altitude=origin.altitude,
                )
                continue

            rank = i if i < self.lead_uav_id else i  # offset within followers
            positions[i] = self._offset(origin, spacing_deg, rank)

        return positions

    def adapt_formation(self, event: Any) -> None:
        """Adapt the formation in response to a swarm event."""
        # TODO: Hafta 3

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _offset(
        self, origin: GeoCoordinate, spacing_deg: float, rank: int
    ) -> GeoCoordinate:
        """Compute a follower position offset from *origin* for the given *rank*."""
        if self.formation_type == FormationType.V_SHAPE:
            return self._v_shape_offset(origin, spacing_deg, rank)
        elif self.formation_type == FormationType.LINE:
            return self._line_offset(origin, spacing_deg, rank)
        elif self.formation_type == FormationType.GRID:
            return self._grid_offset(origin, spacing_deg, rank)
        else:  # DISTRIBUTED
            return self._distributed_offset(origin, spacing_deg, rank)

    @staticmethod
    def _v_shape_offset(
        origin: GeoCoordinate, spacing_deg: float, rank: int
    ) -> GeoCoordinate:
        """Fan followers into a V behind the lead."""
        side = 1 if rank % 2 == 0 else -1
        row = (rank + 1) // 2
        return GeoCoordinate(
            latitude=origin.latitude - row * spacing_deg,
            longitude=origin.longitude + side * row * spacing_deg,
            altitude=origin.altitude,
        )

    @staticmethod
    def _line_offset(
        origin: GeoCoordinate, spacing_deg: float, rank: int
    ) -> GeoCoordinate:
        """Arrange followers in a single file behind the lead."""
        return GeoCoordinate(
            latitude=origin.latitude - rank * spacing_deg,
            longitude=origin.longitude,
            altitude=origin.altitude,
        )

    @staticmethod
    def _grid_offset(
        origin: GeoCoordinate, spacing_deg: float, rank: int
    ) -> GeoCoordinate:
        """Place followers in a square grid."""
        cols = max(1, math.ceil(math.sqrt(rank + 1)))
        row, col = divmod(rank, cols)
        return GeoCoordinate(
            latitude=origin.latitude - row * spacing_deg,
            longitude=origin.longitude + col * spacing_deg,
            altitude=origin.altitude,
        )

    @staticmethod
    def _distributed_offset(
        origin: GeoCoordinate, spacing_deg: float, rank: int
    ) -> GeoCoordinate:
        """Spread followers evenly around a circle centred on the lead."""
        angle = (2 * math.pi * rank) / max(rank, 1)
        return GeoCoordinate(
            latitude=origin.latitude + spacing_deg * math.sin(angle),
            longitude=origin.longitude + spacing_deg * math.cos(angle),
            altitude=origin.altitude,
        )
