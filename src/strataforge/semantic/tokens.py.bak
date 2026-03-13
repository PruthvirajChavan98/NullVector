"""Tokenizer boundary for semantic summarization and decomposition."""

from __future__ import annotations

import importlib
from typing import Protocol


class Tokenizer(Protocol):
    """Stable tokenization boundary for semantic subsystems."""

    identity: str
    supports_exact_counts: bool

    def estimate_tokens(self, text: str) -> int:
        """Return a deterministic token estimate."""

    def count_tokens(self, text: str) -> int:
        """Return a token count using the tokenizer's native strategy."""


class HeuristicTokenizer:
    """Deterministic default tokenizer used throughout the core runtime."""

    identity = "heuristic"
    supports_exact_counts = False

    def estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) * 1.3))

    def count_tokens(self, text: str) -> int:
        return self.estimate_tokens(text)


class OptionalExactTokenizer:
    """Exact tokenizer wrapper that activates only when the optional dependency exists."""

    supports_exact_counts = True

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoding_name = encoding_name
        self.identity = f"tiktoken:{encoding_name}"
        self._heuristic = HeuristicTokenizer()

    def estimate_tokens(self, text: str) -> int:
        return self._heuristic.estimate_tokens(text)

    def count_tokens(self, text: str) -> int:
        try:
            tiktoken = importlib.import_module("tiktoken")
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised in unit tests
            msg = "OptionalExactTokenizer requires the optional 'tiktoken' dependency"
            raise RuntimeError(msg) from exc
        encoding = tiktoken.get_encoding(self._encoding_name)
        return len(encoding.encode(text))


def resolve_tokenizer(tokenizer: Tokenizer | None = None) -> Tokenizer:
    """Return the configured tokenizer or the default heuristic implementation."""

    return tokenizer or HeuristicTokenizer()


__all__ = [
    "HeuristicTokenizer",
    "OptionalExactTokenizer",
    "Tokenizer",
    "resolve_tokenizer",
]
