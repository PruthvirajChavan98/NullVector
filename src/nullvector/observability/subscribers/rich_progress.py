"""Human-readable progress logging configuration for local runs."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TextIO

_GATEWAY_EVENTS = frozenset({"GatewayCallAttempted", "GatewayCallSucceeded", "GatewayCallFailed"})


class ProgressEventFormatter(logging.Formatter):
    """Render structured NullVector events as lightweight progress lines.

    Gateway events include model, image, token, and latency details so that
    each LLM invocation is fully visible in the console stream.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "nullvector_event", None)
        if payload is None:
            return record.getMessage()
        event_name: str = payload["event_name"]
        if event_name in _GATEWAY_EVENTS:
            return self._format_gateway_event(event_name, payload)
        doc = payload.get("document_id") or ""
        suffix = f" document={doc}" if doc else ""
        return f"[{event_name}]{suffix}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_gateway_event(self, event_name: str, payload: dict[str, object]) -> str:
        op = payload.get("operation_name", "")
        model = payload.get("model_name", "")
        # Shorten model name to the part after the last "/" (e.g. provider/model)
        model_short = str(model).rsplit("/", 1)[-1]

        if event_name == "GatewayCallAttempted":
            attempt = payload.get("attempt_number", 1)
            max_att = payload.get("max_attempts", 1)
            raw_paths = payload.get("attachment_paths")
            paths: list[str] = [str(p) for p in raw_paths] if isinstance(raw_paths, list) else []
            images = ", ".join(Path(p).name for p in paths) if paths else "(none)"
            return (
                f"[GatewayCallAttempted]"
                f"  op={op}"
                f"  model={model_short}"
                f"  images={images}"
                f"  attempt={attempt}/{max_att}"
            )

        if event_name == "GatewayCallSucceeded":
            t_in = payload.get("tokens_in", 0)
            t_out = payload.get("tokens_out", 0)
            lat = payload.get("latency_ms", 0)
            return (
                f"[GatewayCallSucceeded]"
                f"  op={op}"
                f"  model={model_short}"
                f"  in={t_in}  out={t_out}"
                f"  latency={lat}ms"
            )

        # GatewayCallFailed
        category = payload.get("failure_category", "UNKNOWN")
        retryable = payload.get("retryable", False)
        attempt = payload.get("attempt_number", 1)
        return (
            f"[GatewayCallFailed]"
            f"  op={op}"
            f"  model={model_short}"
            f"  category={category}"
            f"  retryable={retryable}"
            f"  attempt={attempt}"
        )


def configure_progress_logger(
    *,
    logger: logging.Logger | None = None,
    stream: TextIO | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Attach a progress-stream handler to the provided logger."""

    configured_logger = logger or logging.getLogger("nullvector")
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(ProgressEventFormatter())
    configured_logger.addHandler(handler)
    configured_logger.setLevel(level)
    configured_logger.propagate = False
    return configured_logger


__all__ = ["ProgressEventFormatter", "configure_progress_logger"]
