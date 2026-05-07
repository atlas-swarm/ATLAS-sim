from atlas_common import MessageType
from atlas_communication import CommunicationBus
from atlas_simulation.models import WorldState
from atlas_simulation.simulation_engine import SimulationEngine


def test_publish_world_state_to_bus() -> None:
    bus = CommunicationBus.get_instance()
    bus.message_queue.clear()
    for listeners in bus.subscribers.values():
        listeners.clear()

    received = []
    bus.subscribe(MessageType.WORLD_STATE, received.append)

    world_state = WorldState(
        tick=1,
        uav_states={},
        active_alerts=[],
        timestamp_ms=123456,
    )

    engine = SimulationEngine.get_instance()
    engine._publish_world_state_to_bus(world_state)

    assert received == [world_state]
