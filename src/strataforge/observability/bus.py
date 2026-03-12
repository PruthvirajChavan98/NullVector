"""In-process deterministic event bus."""

from __future__ import annotations

from strataforge.observability.events import FrameworkEvent
from strataforge.observability.subscriber import EventSubscriber


class EventBus:
    """Framework-owned synchronous event bus with deterministic subscriber order."""

    def __init__(self, subscribers: tuple[EventSubscriber, ...] = ()) -> None:
        self._subscribers = subscribers
        self._published_events: list[FrameworkEvent] = []

    @property
    def published_events(self) -> tuple[FrameworkEvent, ...]:
        return tuple(self._published_events)

    def publish(self, event: FrameworkEvent) -> None:
        self._published_events.append(event)
        for subscriber in self._subscribers:
            subscriber.handle(event)


__all__ = ["EventBus"]
