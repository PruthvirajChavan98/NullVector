"""Unit tests for structured logging helpers and formatters."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from nullvector.observability import (
    configure_default_runtime_observability,
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


def test_default_runtime_observability_is_idempotent(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.default_runtime")
    logger.handlers.clear()

    first = configure_default_runtime_observability(
        logger=logger,
        jsonl_path=str(tmp_path / "events.jsonl"),
    )
    second = configure_default_runtime_observability(
        logger=logger,
        jsonl_path=str(tmp_path / "events.jsonl"),
    )

    assert first is logger
    assert second is logger
    assert (
        sum(
            1
            for handler in logger.handlers
            if getattr(handler, "_nullvector_progress_handler", False)
        )
        == 1
    )
    assert (
        sum(
            1 for handler in logger.handlers if getattr(handler, "_nullvector_jsonl_handler", False)
        )
        == 1
    )


def test_default_runtime_observability_honors_env_overrides_and_disable_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = logging.getLogger("nullvector.test.default_runtime.env")
    logger.handlers.clear()
    destination = tmp_path / "env-events.jsonl"
    monkeypatch.setenv("NULLVECTOR_OBSERVABILITY_JSONL_PATH", str(destination))
    monkeypatch.setenv("NULLVECTOR_OBSERVABILITY_LEVEL", "DEBUG")

    configured = configure_default_runtime_observability(logger=logger)

    assert configured is logger
    assert logger.level == logging.DEBUG
    assert destination.exists()

    monkeypatch.setenv("NULLVECTOR_OBSERVABILITY_DISABLE", "1")
    disabled = configure_default_runtime_observability(logger=logger)

    assert disabled is None
    assert not any(
        getattr(handler, "_nullvector_progress_handler", False)
        or getattr(handler, "_nullvector_jsonl_handler", False)
        for handler in logger.handlers
    )


def test_progress_logger_renders_retrieval_events_readably() -> None:
    logger = logging.getLogger("nullvector.test.progress.retrieval")
    logger.handlers.clear()
    stream = io.StringIO()
    configure_progress_logger(logger=logger, stream=stream)

    log_event(
        logger,
        "RetrievalSearchCompleted",
        document_id="d" * 64,
        query="alpha revenue growth",
        limit=5,
        candidate_count=7,
        hit_count=3,
        used_widening=True,
    )

    rendered = stream.getvalue()

    assert "[RetrievalSearchCompleted]" in rendered
    assert f"document={'d' * 64}" in rendered
    assert 'query="alpha revenue growth"' in rendered
    assert "limit=5" in rendered
    assert "candidates=7" in rendered
    assert "hits=3" in rendered
    assert "widened=true" in rendered


def test_jsonl_logger_writes_retrieval_payload_fields(tmp_path: Path) -> None:
    logger = logging.getLogger("nullvector.test.jsonl.retrieval")
    logger.handlers.clear()
    destination = tmp_path / "retrieval-events.jsonl"
    configure_jsonl_logger(str(destination), logger=logger)

    log_event(
        logger,
        "RetrievalQACompleted",
        document_id="d" * 64,
        query="what changed",
        answer_mode="authoritative_text",
        retrieval_hit_count=2,
        citation_count=1,
    )

    payload = json.loads(destination.read_text(encoding="utf-8").splitlines()[0])

    assert payload["event_name"] == "RetrievalQACompleted"
    assert payload["document_id"] == "d" * 64
    assert payload["query"] == "what changed"
    assert payload["answer_mode"] == "authoritative_text"
    assert payload["retrieval_hit_count"] == 2
    assert payload["citation_count"] == 1
