"""Shared text normalization helpers."""

from __future__ import annotations

import string

PUNCTUATION_TO_SPACES = str.maketrans({character: " " for character in string.punctuation})
PUNCTUATION_REMOVAL = str.maketrans("", "", string.punctuation)


def collapse_whitespace(value: str) -> str:
    """Collapse internal whitespace to one space and trim edges."""

    return " ".join(value.split()).strip()


def display_text(value: str) -> str:
    """Return display-stable text with collapsed whitespace."""

    return collapse_whitespace(value)


def normalized_text_key(value: str) -> str:
    """Return a casefolded comparison key that preserves punctuation."""

    return display_text(value).casefold()


def normalize_text(value: str) -> str:
    """Return a casefolded comparison key with punctuation split into spaces."""

    return collapse_whitespace(value.casefold().translate(PUNCTUATION_TO_SPACES))


def casefold_punct_key(value: str) -> str:
    """Return a punctuation-insensitive comparison key."""

    normalized = display_text(value)
    punct_stripped = normalized.casefold().translate(PUNCTUATION_REMOVAL)
    return punct_stripped.strip() or normalized.casefold().strip() or "__empty__"


def tokenize(value: str, *, stopwords: frozenset[str] | None = None) -> tuple[str, ...]:
    """Tokenize normalized text with optional stopword removal."""

    stopwords = stopwords or frozenset()
    return tuple(
        token for token in normalize_text(value).split() if token and token not in stopwords
    )
