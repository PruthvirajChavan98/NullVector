"""Unit tests for the semantic tokenizer boundary."""

from __future__ import annotations

import importlib

import pytest

from strataforge.semantic.tokens import (
    HeuristicTokenizer,
    OptionalExactTokenizer,
    resolve_tokenizer,
)


def test_heuristic_tokenizer_estimate_and_count_match() -> None:
    tokenizer = HeuristicTokenizer()

    assert tokenizer.identity == "heuristic"
    assert tokenizer.supports_exact_counts is False
    assert tokenizer.estimate_tokens("alpha beta gamma") == 3
    assert tokenizer.count_tokens("alpha beta gamma") == 3


def test_resolve_tokenizer_defaults_to_heuristic() -> None:
    tokenizer = resolve_tokenizer()

    assert isinstance(tokenizer, HeuristicTokenizer)


def test_optional_exact_tokenizer_raises_when_dependency_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_import(name: str) -> object:
        del name
        raise ModuleNotFoundError("tiktoken")

    monkeypatch.setattr(importlib, "import_module", missing_import)

    tokenizer = OptionalExactTokenizer()

    with pytest.raises(
        RuntimeError,
        match="OptionalExactTokenizer requires the optional 'tiktoken' dependency",
    ):
        tokenizer.count_tokens("alpha beta gamma")
