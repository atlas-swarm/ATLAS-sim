"""Publisher adapter for optional CommunicationBus integration."""

from __future__ import annotations

from dataclasses import dataclass


TELEMETRY_MESSAGE_TYPE = "TELEMETRY"
WORLD_STATE_MESSAGE_TYPE = "WORLD_STATE"


@dataclass(slots=True)
class PublishedMessage:
    """One published payload entry captured by the adapter."""

    message_type: str
    payload: object


class NullPublisher:
    """Publisher implementation that intentionally discards messages."""

    def publish(self, message_type: str, payload: object) -> None:
        """Discard a message without side effects."""
        del message_type
        del payload


class InMemoryPublisher:
    """Publisher implementation that records messages for tests."""

    def __init__(self) -> None:
        self.published_messages: list[PublishedMessage] = []

    def publish(self, message_type: str, payload: object) -> None:
        """Store a message in memory."""
        self.published_messages.append(PublishedMessage(message_type, payload))

    def reset(self) -> None:
        """Clear all recorded messages."""
        self.published_messages.clear()


_publisher: NullPublisher | InMemoryPublisher = InMemoryPublisher()


def get_publisher() -> NullPublisher | InMemoryPublisher:
    """Return the active publisher implementation."""
    return _publisher


def set_publisher(publisher: NullPublisher | InMemoryPublisher) -> None:
    """Replace the active publisher implementation."""
    global _publisher
    _publisher = publisher


def reset_publisher(use_in_memory: bool = True) -> None:
    """Reset the adapter to a fresh in-memory or null publisher."""
    global _publisher
    _publisher = InMemoryPublisher() if use_in_memory else NullPublisher()


def publish_message(message_type: str, payload: object) -> None:
    """Publish through CommunicationBus when available, otherwise record locally."""
    if _try_publish_to_communication_bus(message_type, payload):
        return
    get_publisher().publish(message_type, payload)


def publish_telemetry(packet: object) -> None:
    """Publish a telemetry payload using the active messaging path."""
    publish_message(TELEMETRY_MESSAGE_TYPE, packet)


def publish_world_state(world_state: object) -> None:
    """Publish a world-state payload using the current adapter."""
    publish_message(WORLD_STATE_MESSAGE_TYPE, world_state)


def dispatch_messages() -> bool:
    """Drain CommunicationBus when the real bus package is present."""
    try:
        from atlas_communication.communication_bus import CommunicationBus
    except ImportError:
        return False

    bus = CommunicationBus.get_instance()
    dispatch = getattr(bus, "dispatch", None)
    if not callable(dispatch):
        return False
    dispatch()
    return True


def get_published_messages() -> list[PublishedMessage]:
    """Return all recorded messages when the adapter is in-memory backed."""
    publisher = get_publisher()
    if isinstance(publisher, InMemoryPublisher):
        return list(publisher.published_messages)
    return []


def _try_publish_to_communication_bus(message_type: str, payload: object) -> bool:
    """Return True when payload was accepted by a real CommunicationBus."""
    try:
        from atlas_communication.communication_bus import CommunicationBus
    except ImportError:
        return False

    bus = CommunicationBus.get_instance()
    resolved_type = _resolve_message_type(message_type)

    try:
        bus.publish(resolved_type, payload)
        return True
    except TypeError:
        return _try_publish_legacy_message(bus, resolved_type, payload)


def _try_publish_legacy_message(
    bus: object,
    message_type: object,
    payload: object,
) -> bool:
    """Support older CommunicationBus.publish(Message(...)) branches."""
    try:
        from atlas_communication.communication_bus import Message
    except ImportError:
        return False

    bus.publish(Message(message_type, payload))
    return True


def _resolve_message_type(message_type: str) -> object:
    """Resolve string names to atlas_common.MessageType when installed."""
    try:
        from atlas_common import MessageType
    except ImportError:
        return message_type
    return getattr(MessageType, message_type, message_type)
