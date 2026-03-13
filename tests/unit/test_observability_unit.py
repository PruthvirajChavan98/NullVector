"""Unit tests for the observability event bus and subscribers."""

from __future__ import annotations

import io
import json
from pathlib import Path

from nullvector.observability import (
    EventBus,
    FrameworkEvent,
    JsonLoggerSubscriber,
    RichProgressSubscriber,
    SourceFingerprintComputed,
)


class CaptureSubscriber:
    """Subscriber that records handled events in order."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def handle(self, event: FrameworkEvent) -> None:
        self.events.append(event.event_name)


def make_event(name: str) -> SourceFingerprintComputed:
    return SourceFingerprintComputed(
        event_id=f"{name}-001",
        event_name=name,
        document_id="d" * 64,
        source_path="/tmp/spec.pdf",
        sha256="a" * 64,
    )


def test_event_bus_preserves_publish_order() -> None:
    subscriber = CaptureSubscriber()
    bus = EventBus(subscribers=(subscriber,))

    bus.publish(make_event("SourceFingerprintComputed"))
    bus.publish(make_event("SourceFingerprintComputedAgain"))

    assert [event.event_name for event in bus.published_events] == [
        "SourceFingerprintComputed",
        "SourceFingerprintComputedAgain",
    ]
    assert subscriber.events == [
        "SourceFingerprintComputed",
        "SourceFingerprintComputedAgain",
    ]


def test_json_logger_subscriber_writes_jsonl(tmp_path: Path) -> None:
    destination = tmp_path / "events.jsonl"
    subscriber = JsonLoggerSubscriber(str(destination))
    subscriber.handle(make_event("SourceFingerprintComputed"))

    lines = destination.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_name"] == "SourceFingerprintComputed"
    assert payload["document_id"] == "d" * 64


def test_rich_progress_subscriber_writes_human_readable_output() -> None:
    stream = io.StringIO()
    subscriber = RichProgressSubscriber(stream=stream)

    subscriber.handle(make_event("SourceFingerprintComputed"))

    assert stream.getvalue() == f"[SourceFingerprintComputed] document={'d' * 64}\n"
