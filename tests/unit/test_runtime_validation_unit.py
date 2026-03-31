"""Unit tests for runtime validation helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nullvector.runtime_validation import validate_writable_root


def test_validate_writable_root_supports_concurrent_probes(tmp_path: Path) -> None:
    root = tmp_path / "observability"

    def _probe() -> None:
        validate_writable_root(str(root), label="concurrent root")

    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in tuple(executor.submit(_probe) for _ in range(32)):
            future.result()

    assert root.exists()
    assert tuple(root.glob(".write-probe*")) == ()
