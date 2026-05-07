from atlas_common import GeoCoordinate, Waypoint
from atlas_swarm.models import UAVCommandType
from atlas_swarm.swarm_coordinator import SwarmCoordinator


class FakeUAV:
    def __init__(self, uav_id: str) -> None:
        self.uav_id = uav_id
        self.received_commands = []

    def receive_command(self, cmd) -> None:
        self.received_commands.append(cmd)


def test_handle_swarm_command_target_all_navigate() -> None:
    coordinator = SwarmCoordinator()
    agents = [FakeUAV("1"), FakeUAV("2")]
    waypoint = Waypoint(coordinate=GeoCoordinate(latitude=39.0, longitude=32.0, altitude=100.0))

    coordinator.handle_swarm_command(
        {
            "command": "NAVIGATE",
            "target": "ALL",
            "waypoint": waypoint,
            "waypoint_index": 0,
        },
        agents=agents,
    )

    for agent in agents:
        assert len(agent.received_commands) == 1
        assert agent.received_commands[0].type == UAVCommandType.NAVIGATE
        assert agent.received_commands[0].payload["waypoints"] == [waypoint]


def test_handle_swarm_command_target_all_rtl() -> None:
    coordinator = SwarmCoordinator()
    agents = [FakeUAV("1"), FakeUAV("2")]

    coordinator.handle_swarm_command(
        {
            "command": "RTL",
            "target": "ALL",
        },
        agents=agents,
    )

    for agent in agents:
        assert len(agent.received_commands) == 1
        assert agent.received_commands[0].type == UAVCommandType.SET_MODE
        assert agent.received_commands[0].payload == {"mode": "RTL"}
