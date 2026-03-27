"""Human-readable progress logging configuration for local runs."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import TextIO

_GATEWAY_EVENTS = frozenset({"GatewayCallAttempted", "GatewayCallSucceeded", "GatewayCallFailed"})
_PROGRESS_HANDLER_ATTR = "_nullvector_progress_handler"
_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("document_id", "document"),
    ("collection_id", "collection"),
    ("acquisition_run_id", "run"),
    ("tree_run_id", "tree"),
    ("retrieval_run_id", "retrieval"),
    ("description_run_id", "description"),
    ("selection_run_id", "selection"),
    ("search_run_id", "search"),
    ("provider_identity", "provider"),
    ("strategy", "strategy"),
    ("search_mode", "mode"),
    ("selection_mode", "mode"),
    ("description_method", "method"),
    ("answer_mode", "answer"),
    ("limit", "limit"),
    ("max_depth", "max_depth"),
    ("step_index", "step"),
    ("page_count", "pages"),
    ("unresolved_region_count", "unresolved"),
    ("committed_node_count", "committed"),
    ("unassigned_span_count", "unassigned"),
    ("unit_count", "units"),
    ("candidate_count", "candidates"),
    ("hit_count", "hits"),
    ("retrieval_hit_count", "hits"),
    ("citation_count", "citations"),
    ("selected_node_count", "selected"),
    ("selected_snippet_count", "preferences"),
    ("source_node_count", "sources"),
    ("clause_count", "clauses"),
    ("metadata_record_count", "records"),
    ("description_count", "descriptions"),
    ("proxy_count", "proxies"),
    ("issue_count", "issues"),
    ("block_count", "blocks"),
    ("title", "title"),
    ("node_id", "node"),
    ("subject_id", "subject"),
    ("region_id", "region"),
    ("used_widening", "widened"),
)
_SEQUENCE_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("frontier_node_ids", "frontier"),
    ("selected_node_ids", "selected_nodes"),
    ("applied_preference_ids", "applied_preferences"),
    ("source_node_ids", "source_nodes"),
)


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
        return self._format_generic_event(event_name, payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_generic_event(self, event_name: str, payload: dict[str, object]) -> str:
        parts = [f"[{event_name}]"]
        query = payload.get("query")
        if isinstance(query, str) and query.strip():
            parts.append(f'query="{self._truncate(query, limit=72)}"')

        rendered_labels: set[str] = set()
        for field_name, label in _FIELD_LABELS:
            value = payload.get(field_name)
            if value is None or value == "" or label in rendered_labels:
                continue
            parts.append(f"{label}={self._render_scalar(value)}")
            rendered_labels.add(label)

        for field_name, label in _SEQUENCE_FIELD_LABELS:
            value = payload.get(field_name)
            if not isinstance(value, Sequence) or isinstance(value, str | bytes):
                continue
            parts.append(f"{label}={len(value)}")

        return " ".join(parts)

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
            images = ", ".join(path.rsplit("/", 1)[-1] for path in paths) if paths else "(none)"
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

    def _render_scalar(self, value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return " ".join(str(value).split())

    def _truncate(self, value: str, *, limit: int = 48) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3]}..."


def configure_progress_logger(
    *,
    logger: logging.Logger | None = None,
    stream: TextIO | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Attach a progress-stream handler to the provided logger."""

    configured_logger = logger or logging.getLogger("nullvector")
    existing_handlers = [
        handler
        for handler in configured_logger.handlers
        if getattr(handler, _PROGRESS_HANDLER_ATTR, False)
    ]
    target_stream = stream or sys.stderr
    if existing_handlers:
        handler = existing_handlers[0]
        if hasattr(handler, "setStream"):
            handler.setStream(target_stream)
        for duplicate in existing_handlers[1:]:
            configured_logger.removeHandler(duplicate)
            duplicate.close()
    else:
        handler = logging.StreamHandler(target_stream)
        setattr(handler, _PROGRESS_HANDLER_ATTR, True)
        configured_logger.addHandler(handler)
    handler.setLevel(level)
    handler.setFormatter(ProgressEventFormatter())
    configured_logger.setLevel(level)
    configured_logger.propagate = False
    return configured_logger


__all__ = ["ProgressEventFormatter", "configure_progress_logger"]
