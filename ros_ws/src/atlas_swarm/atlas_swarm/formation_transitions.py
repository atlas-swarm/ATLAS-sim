from __future__ import annotations

import dataclasses
import math
from atlas_common.enums import FormationType


@dataclasses.dataclass
class MockUAVAgent:
    uav_id: int
    position: tuple = (0.0, 0.0, 100.0)
    battery_level: float = 1.0
    target_position: tuple = (0.0, 0.0, 100.0)
    link_status: str = "OK"


class FormationManager:
    SPACING_DEG = 30.0 / 111_000

    def __init__(self):
        self.formation_type = FormationType.V_SHAPE
        self.lead_uav_id = -1
        self.formation_spacing = 30.0

    def set_formation_type(self, ft):
        self.formation_type = ft
        print(f"  [FormationManager] → {ft.value}")

    def assign_formation_roles(self, agents):
        if not agents:
            return
        lead = max(agents, key=lambda a: a.battery_level)
        self.lead_uav_id = lead.uav_id
        print(f"  [FormationManager] Lead UAV: {lead.uav_id} (battery={lead.battery_level:.2f})")

    def compute_formation_positions(self, agents):
        if not agents:
            return {}
        lead = self.get_lead_uav(agents) or agents[0]
        base_lat, base_lon, base_alt = lead.position
        positions = {lead.uav_id: lead.position}
        followers = [a for a in agents if a.uav_id != lead.uav_id]
        s = self.SPACING_DEG
        for i, agent in enumerate(followers):
            offset = (i + 1) * s
            if self.formation_type == FormationType.V_SHAPE:
                side = 1 if i % 2 == 0 else -1
                pos = (base_lat - offset, base_lon + side * offset, base_alt)
            elif self.formation_type == FormationType.GRID:
                row, col = divmod(i + 1, 2)
                pos = (base_lat - row * s, base_lon + (col - 0.5) * s, base_alt)
            elif self.formation_type == FormationType.LINE:
                pos = (base_lat, base_lon + offset, base_alt)
            else:
                angle = (2 * math.pi / max(len(followers), 1)) * i
                pos = (
                    base_lat + offset * math.cos(angle),
                    base_lon + offset * math.sin(angle),
                    base_alt,
                )
            positions[agent.uav_id] = pos
        return positions

    def get_lead_uav(self, agents):
        return next((a for a in agents if a.uav_id == self.lead_uav_id), None)

    def apply_positions(self, agents):
        positions = self.compute_formation_positions(agents)
        for agent in agents:
            if agent.uav_id in positions:
                agent.target_position = positions[agent.uav_id]

    def transition_to(self, new_type, agents, reason=""):
        print(f"\n[Transition] {self.formation_type.value} → {new_type.value}"
              + (f"  ({reason})" if reason else ""))
        self.set_formation_type(new_type)
        self.assign_formation_roles(agents)
        self.apply_positions(agents)
        self._print_positions(agents)

    def _print_positions(self, agents):
        for a in agents:
            marker = " ★ LEAD" if a.uav_id == self.lead_uav_id else ""
            lat, lon, alt = a.target_position
            print(f"    UAV {a.uav_id}{marker:8s}  lat={lat:.6f}  lon={lon:.6f}  alt={alt:.1f}m")


def run_formation_scenario():
    agents = [
        MockUAVAgent(uav_id=1, position=(39.9000, 32.8000, 100.0), battery_level=0.9),
        MockUAVAgent(uav_id=2, position=(39.9001, 32.8001, 100.0), battery_level=0.7),
        MockUAVAgent(uav_id=3, position=(39.9002, 32.8002, 100.0), battery_level=0.5),
    ]
    fm = FormationManager()
    fm.assign_formation_roles(agents)
    fm.transition_to(FormationType.LINE, agents, "mission start")
    fm.transition_to(FormationType.V_SHAPE, agents, "patrol mode")
    fm.transition_to(FormationType.DISTRIBUTED, agents, "area coverage")
    print("\n[Scenario] UAV 1 battery drops to 0.10 → reassign lead")
    agents[0].battery_level = 0.10
    fm.assign_formation_roles(agents)
    fm.apply_positions(agents)
    fm._print_positions(agents)
    fm.transition_to(FormationType.GRID, agents, "threat detected")
    print("\n[3.2.4] Formasyon geçiş senaryosu tamamlandı ✓")


if __name__ == "__main__":
    run_formation_scenario()
