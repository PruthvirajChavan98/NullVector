"""Unit tests for parallel VLM transcription (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nullvector.domain.ledger import AcquisitionSettings
from nullvector.ingest.vlm_transcriber import PageTranscription, VLMPageTranscriber
from nullvector.llm import (
    GatewayAuditConfig,
    GatewayConfig,
    GatewayService,
    NoopProviderAdapter,
    NoopScriptedResponse,
)

PHASE01_FIXTURES = Path("fixtures/pdfs/phase01")
BORN_DIGITAL = PHASE01_FIXTURES / "born_digital_with_outline.pdf"


def _make_gateway(tmp_path: Path, markdown_text: str = "# Hello\n\nWorld") -> GatewayService:
    return GatewayService(
        GatewayConfig(
            default_model="test-vlm",
            audit=GatewayAuditConfig(persist_root=str(tmp_path / "audit")),
        ),
        provider_adapter=NoopProviderAdapter(
            {
                "vlm_page_transcription": NoopScriptedResponse(
                    output_text=markdown_text,
                ),
            }
        ),
    )


def test_acquisition_settings_vlm_max_concurrent_pages_default() -> None:
    settings = AcquisitionSettings()
    assert settings.vlm_max_concurrent_pages == 4


def test_acquisition_settings_vlm_max_concurrent_pages_custom() -> None:
    settings = AcquisitionSettings(vlm_max_concurrent_pages=8)
    assert settings.vlm_max_concurrent_pages == 8


def test_acquisition_settings_vlm_max_concurrent_pages_rejects_zero() -> None:
    with pytest.raises(ValueError):
        AcquisitionSettings(vlm_max_concurrent_pages=0)


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_parallel_transcription_preserves_page_ordering(tmp_path: Path) -> None:
    gateway = _make_gateway(tmp_path)
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
        max_concurrent_pages=2,
    )

    indices = [r.page_index for r in results]
    assert indices == list(range(len(results)))


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_parallel_transcription_max_concurrent_1_works(tmp_path: Path) -> None:
    """max_concurrent_pages=1 should behave identically to sequential."""
    gateway = _make_gateway(tmp_path)
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
        max_concurrent_pages=1,
    )

    assert isinstance(results, tuple)
    assert len(results) > 0
    for r in results:
        assert isinstance(r, PageTranscription)
        assert r.markdown_text == "# Hello\n\nWorld"


@pytest.mark.skipif(not BORN_DIGITAL.exists(), reason="fixture PDF not present")
def test_parallel_transcription_large_window_works(tmp_path: Path) -> None:
    """Window larger than page count should work fine."""
    gateway = _make_gateway(tmp_path)
    transcriber = VLMPageTranscriber(gateway, dpi=72)

    results = transcriber.transcribe_document(
        str(BORN_DIGITAL),
        document_id="test-doc-id",
        max_concurrent_pages=100,
    )

    assert isinstance(results, tuple)
    assert len(results) > 0
