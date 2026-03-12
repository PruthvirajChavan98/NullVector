"""Subscriber protocol for the framework event bus."""

from __future__ import annotations

from typing import Protocol

from strataforge.observability.events import FrameworkEvent


class EventSubscriber(Protocol):
    """Protocol implemented by synchronous event subscribers."""

    def handle(self, event: FrameworkEvent) -> None:
        """Handle one published event."""


__all__ = ["EventSubscriber"]
