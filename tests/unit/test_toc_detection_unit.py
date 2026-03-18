"""Unit tests for deterministic-first TOC detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nullvector.domain import TocDetectionMethod, TocDetectionResult, TreeSettings
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)
from nullvector.llm.protocols import ProviderAdapter
from nullvector.llm.types import ProviderInvocationRequest, ProviderInvocationResult
from nullvector.tree.headings import PageArtifacts
from nullvector.tree.toc import (
    DETERMINISTIC_LOW_THRESHOLD,
    TocDetector,
)


def rawdict_for_text(text: str) -> dict[str, Any]:
    """Create a minimal rawdict with uniform line styling."""

    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "blocks": [
            {
                "type": 0,
                "bbox": [72.0, 72.0, 540.0, 400.0],
                "lines": [
                    {
                        "bbox": [72.0, 72.0 + index * 18.0, 420.0, 86.0 + index * 18.0],
                        "spans": [
                            {
                                "size": 12.0,
                                "text": line,
                                "chars": [{"c": char} for char in line],
                            }
                        ],
                    }
                    for index, line in enumerate(lines)
                ],
            }
        ]
    }


class CountingProviderAdapter:
    """Wrap a provider adapter and record each invocation."""

    provider_name = "counting"

    def __init__(self, delegate: ProviderAdapter) -> None:
        self._delegate = delegate
        self.calls: list[str] = []

    def invoke(
        self,
        request: ProviderInvocationRequest,
        config: GatewayConfig,
    ) -> ProviderInvocationResult:
        self.calls.append(request.operation_name)
        return self._delegate.invoke(request, config)


def make_gateway(tmp_path: Path, *, is_toc: bool) -> tuple[GatewayService, CountingProviderAdapter]:
    audit_root = tmp_path / "audit"
    delegate = NoopProviderAdapter(
        {
            "toc_detection": NoopScriptedResponse(
                output_json={
                    "is_toc": is_toc,
                    "confidence": 0.87,
                    "reasoning": "page contains TOC-like entries",
                }
            )
        }
    )
    adapter = CountingProviderAdapter(delegate)
    gateway = GatewayService(
        GatewayConfig(
            default_model="test-model",
            audit=GatewayAuditConfig(persist_root=str(audit_root)),
        ),
        provider_adapter=adapter,
    )
    return gateway, adapter


def toc_fixture_pages(*, rawdict: bool = True) -> tuple[PageArtifacts, ...]:
    toc_page_text = "\n".join(
        (
            "Table of Contents",
            "1 Introduction ........ 3",
            "1.1 Scope ........ 4",
            "1.2 Safety ........ 6",
            "2 Operations ........ 9",
        )
    )
    second_toc_page_text = "\n".join(
        (
            "3 Maintenance ........ 12",
            "4 Troubleshooting      18",
        )
    )
    page_one_rawdict = rawdict_for_text(toc_page_text) if rawdict else None
    return (
        PageArtifacts(
            page_index=0,
            text="ACME Manual\nRevision 1\nPrepared by team",
            rawdict=None,
        ),
        PageArtifacts(
            page_index=1,
            text=toc_page_text,
            rawdict=page_one_rawdict,
        ),
        PageArtifacts(
            page_index=2,
            text=second_toc_page_text,
            rawdict=None,
        ),
        PageArtifacts(
            page_index=3,
            text="Introduction\nThis section begins the document body.",
            rawdict=None,
        ),
    )


def test_deterministic_toc_present_requires_no_gateway() -> None:
    detector = TocDetector(TreeSettings())

    result = detector.detect(pages=toc_fixture_pages())

    assert result.toc_page_indices == (1,)
    assert result.detection_method is TocDetectionMethod.DETERMINISTIC
    assert result.has_page_numbers is True
    assert result.toc_content is not None


def test_deterministic_toc_absent_requires_no_gateway() -> None:
    pages = (
        PageArtifacts(page_index=0, text="Foreword\nWelcome to the ACME manual.", rawdict=None),
        PageArtifacts(
            page_index=1,
            text="About This Manual\nThis manual describes safety and operation guidance.",
            rawdict=None,
        ),
        PageArtifacts(
            page_index=2,
            text="Preface\nThis edition updates revision notes and legal notices.",
            rawdict=None,
        ),
    )
    detector = TocDetector(TreeSettings())

    result = detector.detect(pages=pages)

    assert result.toc_page_indices == ()
    assert result.toc_content is None
    assert result.detection_method is TocDetectionMethod.DETERMINISTIC


def test_ambiguous_page_uses_gateway_and_becomes_hybrid(tmp_path: Path) -> None:
    gateway, adapter = make_gateway(tmp_path, is_toc=True)
    detector = TocDetector(TreeSettings(), gateway=gateway)

    result = detector.detect(pages=toc_fixture_pages())

    assert adapter.calls == ["toc_detection"]
    assert result.detection_method is TocDetectionMethod.HYBRID
    assert result.toc_page_indices == (1, 2)
    assert any(score.classified_as_toc for score in result.page_scores if score.page_index == 2)
    audit_files = sorted((tmp_path / "audit").glob("*.json"))
    assert len(audit_files) == 1
    persisted_audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert persisted_audit["operation_name"] == "toc_detection"


def test_toc_detection_persists_replayable_artifact(tmp_path: Path) -> None:
    detector = TocDetector(TreeSettings())

    result = detector.detect(pages=toc_fixture_pages(), artifact_root=str(tmp_path))
    persisted_path = tmp_path / "toc-detection.json"

    assert persisted_path.exists()
    persisted_result = TocDetectionResult.model_validate_json(
        persisted_path.read_text(encoding="utf-8")
    )
    assert persisted_result == result


def test_rawdict_is_optional_and_yields_zero_font_uniformity_signal() -> None:
    detector = TocDetector(TreeSettings())

    result = detector.detect(pages=toc_fixture_pages(rawdict=False))

    page_one_score = next(score for score in result.page_scores if score.page_index == 1)
    assert page_one_score.font_uniformity_signal == 0.0


def test_repeated_header_penalty_prevents_false_positive() -> None:
    pages = (
        PageArtifacts(
            page_index=0,
            text="Company Manual ........ 1\nWelcome to the guide\nRevision notes",
            rawdict=None,
        ),
        PageArtifacts(
            page_index=1,
            text="Company Manual ........ 1\n2 Maintenance      2\n3 Troubleshooting      3",
            rawdict=None,
        ),
        PageArtifacts(
            page_index=2,
            text="Company Manual ........ 1\nGeneral narrative\nAppendix notes",
            rawdict=None,
        ),
    )
    detector = TocDetector(TreeSettings())

    result = detector.detect(pages=pages)

    page_one_score = next(score for score in result.page_scores if score.page_index == 1)
    assert page_one_score.repeated_header_penalty > 0
    assert page_one_score.classified_as_toc is False
    assert page_one_score.final_score < DETERMINISTIC_LOW_THRESHOLD
    assert (
        page_one_score.final_score + page_one_score.repeated_header_penalty * 0.25
        >= DETERMINISTIC_LOW_THRESHOLD
    )
