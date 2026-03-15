"""Unit tests for structured logging helpers and formatters."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from nullvector.observability import (
    configure_jsonl_logger,
    configure_progress_logger,
    log_event,
)


def test_jsonl_logger_writes_structured_events(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.jsonl")
    logger.handlers.clear()
    destination = tmp_path / "events.jsonl"
    configure_jsonl_logger(str(destination), logger=logger)

    log_event(
        logger,
        "SourceFingerprintComputed",
        document_id="d" * 64,
        source_path="/tmp/spec.pdf",
        sha256="a" * 64,
    )

    lines = destination.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_name"] == "SourceFingerprintComputed"
    assert payload["document_id"] == "d" * 64


def test_progress_logger_writes_human_readable_output() -> None:
    logger = logging.getLogger("nullvector.test.progress")
    logger.handlers.clear()
    stream = io.StringIO()
    configure_progress_logger(logger=logger, stream=stream)

    log_event(
        logger,
        "SourceFingerprintComputed",
        document_id="d" * 64,
        source_path="/tmp/spec.pdf",
        sha256="a" * 64,
    )

    assert stream.getvalue() == f"[SourceFingerprintComputed] document={'d' * 64}\n"
