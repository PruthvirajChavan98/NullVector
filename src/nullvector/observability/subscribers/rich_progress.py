"""Human-readable progress subscriber for local CLI and notebook runs."""

from __future__ import annotations

import sys
from typing import TextIO

from nullvector.observability.events import FrameworkEvent


class RichProgressSubscriber:
    """Lightweight progress subscriber with stable text output."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stderr

    def handle(self, event: FrameworkEvent) -> None:
        self._stream.write(f"[{event.event_name}] document={event.document_id}\n")
        self._stream.flush()


__all__ = ["RichProgressSubscriber"]
