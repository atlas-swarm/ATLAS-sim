"""Default publisher adapter used until communication integration exists."""

from __future__ import annotations

from dataclasses import dataclass


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


def publish_world_state(world_state: object) -> None:
    """Publish a world-state payload using the current adapter."""
    get_publisher().publish(WORLD_STATE_MESSAGE_TYPE, world_state)


def get_published_messages() -> list[PublishedMessage]:
    """Return all recorded messages when the adapter is in-memory backed."""
    publisher = get_publisher()
    if isinstance(publisher, InMemoryPublisher):
        return list(publisher.published_messages)
    return []
