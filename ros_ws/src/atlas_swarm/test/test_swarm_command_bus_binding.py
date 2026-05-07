from atlas_common import GeoCoordinate, MessageType, Waypoint
from atlas_communication import CommunicationBus
from atlas_swarm.models import UAVCommandType
from atlas_swarm.swarm_coordinator import SwarmCoordinator


class FakeUAV:
    def __init__(self, uav_id: str) -> None:
        self.uav_id = uav_id
        self.received_commands = []

    def receive_command(self, cmd) -> None:
        self.received_commands.append(cmd)


def test_bind_command_bus_dispatches_to_fake_uavs() -> None:
    bus = CommunicationBus.get_instance()
    bus.message_queue.clear()
    for listeners in bus.subscribers.values():
        listeners.clear()

    agents = [FakeUAV("1"), FakeUAV("2")]
    coordinator = SwarmCoordinator()
    coordinator.bind_command_bus(bus=bus, agents=agents)

    waypoint = Waypoint(coordinate=GeoCoordinate(latitude=39.0, longitude=32.0, altitude=100.0))
    bus.publish(
        MessageType.SWARM_COMMAND,
        {
            "command": "NAVIGATE",
            "target": "ALL",
            "waypoint": waypoint,
            "waypoint_index": 0,
        },
    )
    bus.dispatch()

    for agent in agents:
        assert len(agent.received_commands) == 1
        assert agent.received_commands[0].type == UAVCommandType.NAVIGATE
